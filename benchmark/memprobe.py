import sys, glob, os
sys.path.insert(0,sys.argv[1])
import puremagic
paths=sorted(glob.glob('/usr/share/doc/nodejs/api/*.html'))[:200]+sorted(glob.glob('/usr/lib/python3.12/**/*.py',recursive=True))[:300]
for p in paths:
    try: puremagic.magic_string(open(p,'rb').read())
    except Exception: pass
