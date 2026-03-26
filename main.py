import argparse

from app.bootstrap import run


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析します。"""

    parser = argparse.ArgumentParser(description="freee OAuth token bootstrap utility")
    parser.add_argument(
        "--auth-code",
        default=None,
        help="Authorization code obtained from the browser flow",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    raise SystemExit(run(auth_code=args.auth_code))
