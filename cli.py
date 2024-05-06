from subprocess import call
from sys import argv


def execute():
    options = argv[1:]
    call(['sh', 'amebo.sh', *options])


if __name__ == '__main__':
    execute()
