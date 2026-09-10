"""Entry point wrapper: python start.py [coursera_dl args...]"""
import sys

from coursera_dl import main_f

if __name__ == '__main__':
    main_f(sys.argv[1:])