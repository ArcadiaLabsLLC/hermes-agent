//! ripgrep's matcher behind a C ABI: bytes in, matching line numbers out (ABI version 1).
//!
//! Plan `docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md` §5, row
//! `RT-PHONE-REGEX-SEARCH-RUNS-RIPGREPS-MATCHER-FROM-A-NATIVE-LIBRARY`. The header is
//! `include/project_files_match.h`; the one caller is `agent_runtime/project_files/native_match.py`.
//!
//! * **Bytes, never a path.** Python opens, caps and checks each file and hands over its bytes, so
//!   nothing here can follow a link, walk a folder or write.
//! * **ripgrep's matcher.** `grep-regex` (what `rg` runs) over `grep-searcher`, with `\n` as the line
//!   terminator (the searcher's fast line path) and CRLF anchors, so `$` matches before a `\r\n`.
//! * **Bounded.** The compiled program's size, the lazy DFA's cache and the nesting depth are capped
//!   at compile time; a search stops at its cancel byte, at its time budget, or at `lines_cap` lines,
//!   handing back where to resume.
//! * **No unwind crosses the ABI.** Every `extern "C"` function runs its body under
//!   [`std::panic::catch_unwind`] and answers a panic with an error code; the release profile
//!   unwinds (Cargo.toml), so a Rust panic never ends the Hermes process that loaded the library.

use std::panic::{catch_unwind, AssertUnwindSafe};
use std::sync::atomic::{AtomicU8, Ordering};
use std::time::{Duration, Instant};

use grep_regex::{RegexMatcher, RegexMatcherBuilder};
use grep_searcher::{BinaryDetection, Searcher, SearcherBuilder, Sink, SinkMatch};

/// The ABI this library speaks; the binding refuses any other.
pub const ABI_VERSION: i32 = 1;

/// `pfm_compile` flag: match without regard to case.
pub const FLAG_IGNORE_CASE: u32 = 1;

/// The deepest nesting a pattern may hold.
pub const NEST_LIMIT: u32 = 64;

/// `pfm_search`: the cancel byte was set.
pub const CANCELLED: i64 = -1;
/// `pfm_search`: the time budget ran out.
pub const BUDGET_SPENT: i64 = -2;
/// `pfm_search`: the handle was NULL. A freed handle cannot be told from a live one; the binding
/// holds each handle in one object that frees it once and never passes it after.
pub const BAD_HANDLE: i64 = -3;
/// `pfm_search`: a NULL buffer with a length, `start` past the end, or no room for one line.
pub const BAD_ARGUMENT: i64 = -4;
/// Any function: a panic was caught at the ABI boundary.
pub const PANICKED: i64 = -5;
/// `pfm_search`: the searcher refused the search (a configuration error).
pub const SEARCH_FAILED: i64 = -6;

/// A compiled pattern: what `pfm_compile` hands out and `pfm_free` takes back.
#[derive(Debug)]
pub struct Pattern {
    matcher: RegexMatcher,
}

/// Runs `body`, answering a panic with `fallback` instead of unwinding into C.
fn guard<T>(fallback: T, body: impl FnOnce() -> T) -> T {
    // MUTATION: call `body()` bare and a panic unwinds into the C caller (test: a_panic_is_answered_with_its_code).
    catch_unwind(AssertUnwindSafe(body)).unwrap_or(fallback)
}

/// Compiles `pattern` under the caps, or the engine's own sentence for why it is refused.
pub fn compile(pattern: &str, flags: u32, size_limit: usize, dfa_limit: usize) -> Result<Pattern, String> {
    if flags & !FLAG_IGNORE_CASE != 0 {
        return Err(format!("unknown compile flags {flags:#x}"));
    }
    // As `rg` builds it: `multi_line(true)` makes `^` and `$` line anchors (not "search across
    // lines": that is the searcher's setting, left off). Order matters below: `crlf(true)` sets CRLF
    // anchors AND a `\r\n` terminator; the `line_terminator` after it puts the terminator back to
    // `\n` (grep-regex's documented way to have both), which keeps the searcher's fast line path and
    // its default `\n` terminator.
    // MUTATION: drop `.crlf(true)` and `milk$` misses "buy milk\r\n" (test: dollar_matches_before_crlf).
    RegexMatcherBuilder::new()
        .multi_line(true)
        .crlf(true)
        .line_terminator(Some(b'\n'))
        .case_insensitive(flags & FLAG_IGNORE_CASE != 0)
        // MUTATION: drop the size limit and `\p{L}{30}c` compiles at a 1 MiB cap (test: a_pattern_past_the_size_cap_is_refused).
        .size_limit(size_limit)
        .dfa_size_limit(dfa_limit)
        .nest_limit(NEST_LIMIT)
        .build(pattern)
        .map(|matcher| Pattern { matcher })
        .map_err(|error| error.to_string())
}

/// Why a search stopped before the end of its buffer.
#[derive(Debug, PartialEq, Eq, Clone, Copy)]
enum Stop {
    Cancelled,
    Spent,
}

/// The sink: writes each matching line's number, stopping at the cap, the cancel byte or the budget.
struct Lines<'a> {
    out: &'a mut [u64],
    written: usize,
    first_line: u64,
    start: usize,
    cancel: Option<&'a AtomicU8>,
    ends: Instant,
    stop: Option<Stop>,
    resume: Option<(usize, u64)>,
}

impl Lines<'_> {
    fn interrupted(&mut self) -> bool {
        if self.cancel.is_some_and(|flag| flag.load(Ordering::Acquire) != 0) {
            self.stop = Some(Stop::Cancelled);
        } else if Instant::now() >= self.ends {
            self.stop = Some(Stop::Spent);
        }
        self.stop.is_some()
    }
}

impl Sink for Lines<'_> {
    type Error = std::io::Error;

    fn matched(&mut self, _searcher: &Searcher, found: &SinkMatch<'_>) -> Result<bool, Self::Error> {
        // MUTATION: never read the cancel byte here and a set byte is ignored until the end
        // (test: a_cancel_set_during_a_search_stops_it).
        if self.interrupted() {
            return Ok(false);
        }
        let mut number = self.first_line - 1 + found.line_number().unwrap_or(1);
        let mut offset = self.start + found.absolute_byte_offset() as usize;
        for line in found.lines() {
            if self.written == self.out.len() {
                // MUTATION: stop without a resume point and a file past the cap is cut short
                // (test: a_buffer_past_the_cap_resumes_where_it_stopped).
                self.resume = Some((offset, number));
                return Ok(false);
            }
            self.out[self.written] = number;
            self.written += 1;
            number += 1;
            offset += line.len();
        }
        Ok(true)
    }
}

/// The outcome of [`search`]: lines written, and where to resume when the cap stopped it.
#[derive(Debug, PartialEq, Eq)]
pub struct Found {
    pub written: usize,
    pub resume: Option<(usize, u64)>,
}

/// Searches `bytes[start..]` (whose first line is numbered `first_line`) for `pattern`, writing
/// matching line numbers to `out`. `Err` carries the ABI's negative code.
pub fn search(pattern: &Pattern, bytes: &[u8], start: usize, first_line: u64, cancel: Option<&AtomicU8>,
              budget: Duration, out: &mut [u64]) -> Result<Found, i64> {
    if start > bytes.len() || out.is_empty() || first_line == 0 {
        return Err(BAD_ARGUMENT);
    }
    let ends = Instant::now() + budget;
    let mut sink = Lines { out, written: 0, first_line, start, cancel, ends, stop: None, resume: None };
    // The bytes are Python's checked UTF-8 text: no binary detection, and no BOM sniffing, which
    // would transcode and move the byte offsets a resume is given.
    let mut searcher = SearcherBuilder::new()
        .line_number(true)
        .binary_detection(BinaryDetection::none())
        .bom_sniffing(false)
        .build();
    if sink.interrupted() {
        return Err(stop_code(sink.stop));
    }
    if searcher.search_slice(&pattern.matcher, &bytes[start..], &mut sink).is_err() {
        return Err(SEARCH_FAILED);
    }
    if sink.stop.is_some() || (sink.resume.is_none() && sink.interrupted()) {
        return Err(stop_code(sink.stop));
    }
    Ok(Found { written: sink.written, resume: sink.resume })
}

fn stop_code(stop: Option<Stop>) -> i64 {
    match stop {
        Some(Stop::Cancelled) => CANCELLED,
        _ => BUDGET_SPENT,
    }
}

fn write_error(message: &str, err: *mut u8, err_cap: usize, err_len: *mut usize) {
    let mut cut = message.len().min(err_cap);
    while !message.is_char_boundary(cut) {
        cut -= 1;
    }
    if !err.is_null() && cut > 0 {
        // SAFETY: the caller gives `err` room for `err_cap` bytes; `cut <= err_cap`.
        unsafe { std::ptr::copy_nonoverlapping(message.as_ptr(), err, cut) };
    }
    if !err_len.is_null() {
        // SAFETY: the caller gives a writable `size_t` or NULL.
        unsafe { *err_len = if err.is_null() { 0 } else { cut } };
    }
}

/// The ABI version: 1.
#[no_mangle]
pub extern "C" fn pfm_abi_version() -> i32 {
    guard(PANICKED as i32, || ABI_VERSION)
}

/// Compiles the UTF-8 `pattern` (`len` bytes). NULL when it is refused, with the engine's sentence in
/// `err` (at most `err_cap` bytes, cut on a character boundary, its length in `*err_len`).
///
/// # Safety
/// `pattern` points at `len` readable bytes; `err` at `err_cap` writable bytes or NULL; `err_len` at a
/// writable `size_t` or NULL.
#[no_mangle]
pub unsafe extern "C" fn pfm_compile(pattern: *const u8, len: usize, flags: u32, size_limit: usize,
                                     dfa_limit: usize, err: *mut u8, err_cap: usize,
                                     err_len: *mut usize) -> *mut Pattern {
    guard(std::ptr::null_mut(), || {
        if pattern.is_null() {
            write_error("the pattern is NULL", err, err_cap, err_len);
            return std::ptr::null_mut();
        }
        // SAFETY: the caller's contract above.
        let bytes = unsafe { std::slice::from_raw_parts(pattern, len) };
        let compiled = std::str::from_utf8(bytes)
            .map_err(|_| "the pattern is not UTF-8 text".to_string())
            .and_then(|text| compile(text, flags, size_limit, dfa_limit));
        match compiled {
            Ok(compiled) => {
                write_error("", err, err_cap, err_len);
                Box::into_raw(Box::new(compiled))
            }
            Err(message) => {
                write_error(&message, err, err_cap, err_len);
                std::ptr::null_mut()
            }
        }
    })
}

/// Searches `bytes[start..len]`, whose first line is numbered `first_line` (from 1), writing up to
/// `lines_cap` matching line numbers to `lines_out`. Returns the count written, or a negative code
/// (`-1` cancelled, `-2` budget spent, `-3` NULL handle, `-4` bad argument, `-5` panic, `-6` search
/// failed). `*resume_line` is 0 when the buffer was searched to its end; otherwise the cap stopped
/// the search, and the next call passes `start = *resume_at`, `first_line = *resume_line`.
/// `cancel` (or NULL) is read before the search, at each match and at the end; `budget_ms` is the time
/// the search may take (0 is already spent).
///
/// # Safety
/// `matcher` is NULL or a live handle from `pfm_compile`; `bytes` points at `len` readable bytes;
/// `cancel` is NULL or a readable byte; `lines_out` points at `lines_cap` writable `uint64_t`s;
/// `resume_at` and `resume_line` are writable.
#[no_mangle]
pub unsafe extern "C" fn pfm_search(matcher: *const Pattern, bytes: *const u8, len: usize, start: usize,
                                    first_line: u64, cancel: *const u8, budget_ms: u32,
                                    lines_out: *mut u64, lines_cap: usize, resume_at: *mut usize,
                                    resume_line: *mut u64) -> i64 {
    guard(PANICKED, || {
        // MUTATION: drop the NULL check and a NULL handle is dereferenced (test: a_null_handle_is_refused).
        if matcher.is_null() {
            return BAD_HANDLE;
        }
        if (bytes.is_null() && len > 0) || lines_out.is_null() || resume_at.is_null() || resume_line.is_null() {
            return BAD_ARGUMENT;
        }
        // SAFETY: the caller's contract above; an empty buffer may be NULL.
        let (pattern, haystack, out) = unsafe {
            let haystack: &[u8] = if len == 0 { &[] } else { std::slice::from_raw_parts(bytes, len) };
            (&*matcher, haystack, std::slice::from_raw_parts_mut(lines_out, lines_cap))
        };
        // SAFETY: a byte the caller owns for the call; read atomically, since another thread sets it.
        let flag = if cancel.is_null() { None } else { Some(unsafe { AtomicU8::from_ptr(cancel as *mut u8) }) };
        let budget = Duration::from_millis(u64::from(budget_ms));
        match search(pattern, haystack, start, first_line, flag.map(|f| &*f), budget, out) {
            Ok(found) => {
                let (at, line) = found.resume.unwrap_or((0, 0));
                // SAFETY: checked non-NULL above.
                unsafe {
                    *resume_at = at;
                    *resume_line = line;
                }
                found.written as i64
            }
            Err(code) => code,
        }
    })
}

/// Frees a handle from `pfm_compile`; NULL is a no-op.
///
/// # Safety
/// `matcher` is NULL or a live handle, freed at most once.
#[no_mangle]
pub unsafe extern "C" fn pfm_free(matcher: *mut Pattern) {
    guard((), || {
        if !matcher.is_null() {
            // SAFETY: the caller's contract above.
            drop(unsafe { Box::from_raw(matcher) });
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const MIB: usize = 1 << 20;
    const LONG: Duration = Duration::from_secs(30);

    fn pattern(text: &str) -> Pattern {
        compile(text, 0, MIB, 8 * MIB).expect("compiles")
    }

    fn all_lines(pattern: &Pattern, text: &str) -> Vec<u64> {
        let mut out = vec![0u64; 1024];
        let found = search(pattern, text.as_bytes(), 0, 1, None, LONG, &mut out).expect("searched");
        assert_eq!(found.resume, None);
        out.truncate(found.written);
        out
    }

    /// The same engine asked one line at a time: what each line number must be.
    fn oracle(text: &str, regex: &str) -> Vec<u64> {
        let line = regex::Regex::new(regex).unwrap();
        text.split('\n')
            .map(|l| l.strip_suffix('\r').unwrap_or(l))
            .enumerate()
            .filter(|(index, l)| line.is_match(l) && !(l.is_empty() && *index == text.split('\n').count() - 1))
            .map(|(index, _)| index as u64 + 1)
            .collect()
    }

    #[test]
    fn line_numbers_match_the_engine_asked_per_line() {
        let text = "fn main() {\n    let x = 1;\n}\nfn helper(a: u8) -> u8 { a }\n// fn not_here\nend";
        for regex in [r"fn\s+(\w+)\(", r"^fn", r"\}$", r"[0-9]", r"not_\w+", r"^end$", r"zzz"] {
            assert_eq!(all_lines(&pattern(regex), text), oracle(text, regex), "{regex}");
        }
    }

    #[test]
    fn dollar_matches_before_crlf() {
        let text = "buy milk\r\ncall mum\r\n";
        assert_eq!(all_lines(&pattern("milk$"), text), vec![1]);
        assert_eq!(all_lines(&pattern("^call mum$"), text), vec![2]);
    }

    #[test]
    fn ignore_case_is_a_flag() {
        let loud = compile("MILK", FLAG_IGNORE_CASE, MIB, 8 * MIB).unwrap();
        assert_eq!(all_lines(&loud, "buy milk\n"), vec![1]);
        assert_eq!(all_lines(&pattern("MILK"), "buy milk\n"), Vec::<u64>::new());
        assert!(compile("x", 2, MIB, MIB).unwrap_err().contains("unknown compile flags"));
    }

    #[test]
    fn a_literal_newline_is_refused_with_ripgreps_sentence() {
        let refused = compile(r"a\nb", 0, MIB, MIB).err().expect("refused");
        assert!(refused.contains(r#"the literal '"\n"' is not allowed in a regex"#)
                || refused.contains(r#"the literal "\n" is not allowed in a regex"#), "{refused}");
    }

    #[test]
    fn a_pattern_past_the_size_cap_is_refused() {
        let refused = compile(r"\p{L}{30}c", 0, MIB, 8 * MIB).err().expect("refused");
        assert!(refused.contains("exceeds size limit"), "{refused}");
        assert!(compile(r"\p{L}{8}c", 0, MIB, 8 * MIB).is_ok());
        assert!(compile("(", 0, MIB, MIB).unwrap_err().contains("unclosed group"));
    }

    #[test]
    fn a_pattern_nested_past_the_limit_is_refused() {
        let deep = "(".repeat(NEST_LIMIT as usize + 2) + &")".repeat(NEST_LIMIT as usize + 2);
        assert!(compile(&deep, 0, MIB, MIB).unwrap_err().contains("nest"));
    }

    #[test]
    fn a_buffer_past_the_cap_resumes_where_it_stopped() {
        let text: String = (1..=10).map(|n| if n % 2 == 0 { format!("hit {n}\n") } else { format!("miss {n}\n") }).collect();
        let hits = pattern("^hit");
        let mut out = [0u64; 2];
        let (mut start, mut first, mut every) = (0usize, 1u64, Vec::new());
        loop {
            let found = search(&hits, text.as_bytes(), start, first, None, LONG, &mut out).unwrap();
            every.extend_from_slice(&out[..found.written]);
            match found.resume {
                Some((at, line)) => (start, first) = (at, line),
                None => break,
            }
        }
        assert_eq!(every, vec![2, 4, 6, 8, 10]);
    }

    #[test]
    fn a_set_cancel_byte_or_a_spent_budget_stops_the_search() {
        let flag = AtomicU8::new(1);
        let mut out = [0u64; 4];
        assert_eq!(search(&pattern("a"), b"a\n", 0, 1, Some(&flag), LONG, &mut out), Err(CANCELLED));
        assert_eq!(search(&pattern("a"), b"a\n", 0, 1, None, Duration::ZERO, &mut out), Err(BUDGET_SPENT));
    }

    #[test]
    fn a_cancel_set_during_a_search_stops_it() {
        let text = "a\n".repeat(MIB);
        let flag = AtomicU8::new(0);
        let mut out = vec![0u64; 2 * MIB];
        let every_a = pattern("a");
        let whole = Instant::now();
        search(&every_a, text.as_bytes(), 0, 1, Some(&flag), LONG, &mut out).expect("searched");
        let whole = whole.elapsed();
        let started = Instant::now();
        let stopped = std::thread::scope(|scope| {
            scope.spawn(|| {
                std::thread::sleep(whole / 20);
                flag.store(1, Ordering::Release);
            });
            search(&every_a, text.as_bytes(), 0, 1, Some(&flag), LONG, &mut out)
        });
        let took = started.elapsed();
        assert_eq!(stopped, Err(CANCELLED));
        // Stopped at a match soon after the byte was set, not at the end of the buffer.
        assert!(took < whole / 2, "cancelled after {took:?}; the whole search takes {whole:?}");
    }

    #[test]
    fn a_null_handle_is_refused() {
        let mut out = [0u64; 1];
        let (mut at, mut line) = (0usize, 0u64);
        let code = unsafe {
            pfm_search(std::ptr::null(), b"a".as_ptr(), 1, 0, 1, std::ptr::null(), 1000, out.as_mut_ptr(), 1,
                       &mut at, &mut line)
        };
        assert_eq!(code, BAD_HANDLE);
    }

    #[test]
    fn the_abi_round_trips_and_reports_refusals_in_words() {
        assert_eq!(pfm_abi_version(), 1);
        let mut err = [0u8; 256];
        let mut err_len = 0usize;
        let bad = unsafe { pfm_compile(b"(".as_ptr(), 1, 0, MIB, MIB, err.as_mut_ptr(), err.len(), &mut err_len) };
        assert!(bad.is_null());
        assert!(std::str::from_utf8(&err[..err_len]).unwrap().contains("unclosed group"));
        let good = unsafe { pfm_compile(b"b+".as_ptr(), 2, 0, MIB, MIB, err.as_mut_ptr(), err.len(), &mut err_len) };
        assert!(!good.is_null() && err_len == 0);
        let text = b"a\nbb\nc\nb\n";
        let mut out = [0u64; 1];
        let (mut at, mut line) = (0usize, 0u64);
        let n = unsafe { pfm_search(good, text.as_ptr(), text.len(), 0, 1, std::ptr::null(), 1000, out.as_mut_ptr(), 1, &mut at, &mut line) };
        assert_eq!((n, out[0], at, line), (1, 2, 7, 4));
        let n = unsafe { pfm_search(good, text.as_ptr(), text.len(), at, line, std::ptr::null(), 1000, out.as_mut_ptr(), 1, &mut at, &mut line) };
        assert_eq!((n, out[0], line), (1, 4, 0));
        unsafe { pfm_free(good) };
        unsafe { pfm_free(std::ptr::null_mut()) };
    }

    #[test]
    fn a_panic_is_answered_with_its_code() {
        let quiet = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let answered = guard(PANICKED, || -> i64 { panic!("boom") });
        std::panic::set_hook(quiet);
        assert_eq!(answered, PANICKED);
    }

    #[test]
    fn linear_time_on_backtracking_traps() {
        let text = format!("{}b\n", "a".repeat(64 * 1024)).repeat(16);
        for trap in [r"(a|aa)+$", r"(a*)*c", r"(\w+\s*)+x$"] {
            let started = Instant::now();
            all_lines(&pattern(trap), &text);
            assert!(started.elapsed() < Duration::from_secs(2), "{trap} took {:?}", started.elapsed());
        }
    }
}
