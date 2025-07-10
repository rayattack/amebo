from pathlib import Path
from subprocess import call
from sys import argv, executable


def execute():
    options = argv[1:]
    cwd = Path(__file__).parent.resolve()
    call(['sh', Path.joinpath(cwd, 'amebo.sh'), *options], executable='/bin/bash')


if __name__ == '__main__':
    execute()

