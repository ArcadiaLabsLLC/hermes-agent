"""Native checkpoint configuration under the caller's active profile."""

__layer__ = "stores"


def checkpoint_configuration():
    from hermes_cli.config import DEFAULT_CONFIG, load_config
    config = load_config().get("checkpoints", {})
    if isinstance(config, bool):
        config = {"enabled": config}
    if not isinstance(config, dict):
        config = {}
    return {**DEFAULT_CONFIG["checkpoints"], **config}


def checkpoint_constructor_kwargs():
    config = checkpoint_configuration()
    return {"checkpoints_enabled": config["enabled"],
            **{f"checkpoint_{name}": config[name]
               for name in ("max_snapshots", "max_total_size_mb", "max_file_size_mb")}}
