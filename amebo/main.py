from pathlib import Path
from subprocess import call
from sys import argv


def execute():
    options = argv[1:]
    cwd = Path(__file__).parent.resolve()
    call(['sh', f'{cwd}/amebo.sh', *options])


if __name__ == '__main__':
    execute()
