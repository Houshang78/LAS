"""LAS Desktop-Client Entry-Point.

Wird vom `/usr/bin/las` Wrapper aufgerufen (`python3 -m lotto_analyzer.client`).
Eigener Entry hier statt im Namespace-Root, damit es nicht mit dem
LASS-Server-Paket kollidiert (das nimmt `lotto_analyzer/__main__.py`).

Logik gespiegelt aus `lotto_analyzer/__main__.py` im LAS-Repo — der
bleibt für lokales `PYTHONPATH=src python -m lotto_analyzer` während
der Entwicklung erhalten, wird aber NICHT vom .deb installiert.
"""

import argparse
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="las",
        description="lotto-analyzer System (GTK4 Desktop Client)",
    )
    parser.add_argument(
        "--server", type=str, default=None,
        help="Server-Adresse (z.B. 192.168.1.100:8049)",
    )
    parser.add_argument(
        "--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None, help="Log-Level",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Debug-Modus",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    from lotto_common.config import ConfigManager
    config_mgr = ConfigManager()
    cfg = config_mgr.load()

    from lotto_common.utils.logging_config import setup_logging, get_logger

    log_level = "DEBUG" if args.debug else (args.log_level or cfg.logging.level)
    log_cfg = cfg.logging

    setup_logging(
        level=log_level,
        log_dir=log_cfg.log_dir,
        fallback_dir=log_cfg.fallback_log_dir or str(config_mgr.data_dir / "logs"),
        enable_file_logging=log_cfg.enable_file_logging,
        max_bytes=log_cfg.max_file_size_mb * 1024 * 1024,
        backup_count=log_cfg.backup_count,
    )

    logger = get_logger("main")

    server_addr = args.server
    if not server_addr:
        server_addr = f"{cfg.server.host}:{cfg.server.port}"

    logger.info("lotto-analyzer (Desktop) startet, Server: %s", server_addr)

    from lotto_analyzer.ui.app import LottoAnalyzerApp
    app = LottoAnalyzerApp(server_address=server_addr)
    app.run(sys.argv[:1])


if __name__ == "__main__":
    main()
