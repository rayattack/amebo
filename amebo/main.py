from pathlib import Path
from subprocess import call
from sys import argv, executable


def execute():
    options = argv[1:]
    script_dir = Path(__file__).parent.resolve()
    script_path = Path.joinpath(script_dir, 'amebo.sh')
    # Run the script in the user's current directory, not the script's directory
    call(['sh', script_path, *options], executable='/bin/bash')


if __name__ == '__main__':
    execute()
