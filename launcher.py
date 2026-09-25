"""실행 파일(exe) 진입점. 소스에서 바로 실행할 때는 `python -m hd2mm` 을 써도 된다."""
import sys

from hd2mm.app import main

if __name__ == "__main__":
    sys.exit(main())
