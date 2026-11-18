"""Gravador que acompanha o programa. Precisa de console próprio para entregar o vídeo ao Clipador."""
import sys

from streamlink_cli.main import main

if __name__ == "__main__":
    sys.exit(main())
