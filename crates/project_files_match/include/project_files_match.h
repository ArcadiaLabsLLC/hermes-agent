/* project_files_match.h: ABI version 1.
 *
 * ripgrep's matcher (grep-regex over grep-searcher) behind a plain C ABI: bytes in, matching line
 * numbers out. The library never takes a path, never walks a folder, never writes and never starts
 * a process. No Rust panic crosses these functions: each answers one with an error code.
 *
 * The one caller today is hermes' agent_runtime/project_files/native_match.py (ctypes). Plan
 * docs/agent-runtime-harness/planned/phone-regex-engine-in-process-2026-11-21.md section 5.
 */
#ifndef PROJECT_FILES_MATCH_H
#define PROJECT_FILES_MATCH_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define PFM_ABI_VERSION 1

/* pfm_compile flags */
#define PFM_IGNORE_CASE 1u

/* pfm_search codes (a count written is >= 0) */
#define PFM_CANCELLED     (-1) /* the cancel byte was set */
#define PFM_BUDGET_SPENT  (-2) /* budget_ms ran out */
#define PFM_BAD_HANDLE    (-3) /* the handle was NULL (a freed handle cannot be detected: never pass one) */
#define PFM_BAD_ARGUMENT  (-4) /* a NULL buffer with a length, start past the end, lines_cap 0, first_line 0 */
#define PFM_PANICKED      (-5) /* a panic was caught at the boundary */
#define PFM_SEARCH_FAILED (-6) /* the searcher refused the search */

typedef struct pfm_pattern pfm_pattern;

int32_t pfm_abi_version(void);

/* Compiles the UTF-8 pattern (len bytes) with \n as the line terminator and CRLF anchors, under the
 * compiled-size cap size_limit, the lazy DFA cache cap dfa_limit and a nesting limit of 64. NULL when
 * refused; the engine's sentence is written to err (at most err_cap bytes, cut on a character
 * boundary) and its length to *err_len. */
pfm_pattern *pfm_compile(const uint8_t *pattern, size_t len, uint32_t flags, size_t size_limit,
                         size_t dfa_limit, uint8_t *err, size_t err_cap, size_t *err_len);

/* Searches bytes[start..len], whose first line is numbered first_line (from 1), writing up to
 * lines_cap matching line numbers to lines_out, ascending. Returns the count written or a code above.
 * *resume_line is 0 when the buffer was searched to its end; otherwise lines_cap stopped the search
 * and the next call passes start = *resume_at, first_line = *resume_line. cancel (or NULL) is read
 * before the search, at each match and at the end; budget_ms is the time the call may take. */
int64_t pfm_search(const pfm_pattern *matcher, const uint8_t *bytes, size_t len, size_t start,
                   uint64_t first_line, const uint8_t *cancel, uint32_t budget_ms, uint64_t *lines_out,
                   size_t lines_cap, size_t *resume_at, uint64_t *resume_line);

/* Frees a handle from pfm_compile, at most once; NULL is a no-op. */
void pfm_free(pfm_pattern *matcher);

#ifdef __cplusplus
}
#endif

#endif /* PROJECT_FILES_MATCH_H */
