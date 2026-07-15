"""KiCad IPC action entrypoint."""

from plugin_bootstrap import bootstrap_vendor

bootstrap_vendor()

from jlceda2kicad.main import run  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run())
