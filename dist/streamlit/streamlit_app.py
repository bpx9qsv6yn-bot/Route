"""Launch the complete, readable FairRoute source bundle on Streamlit Cloud."""
from pathlib import Path
import hashlib
import os
import runpy
import sys
import tempfile
import zipfile
import streamlit as st

BUNDLE = Path(__file__).with_name('fairroute-source.zip')

@st.cache_resource
def unpack_source(digest):
    target = Path(tempfile.mkdtemp(prefix='fairroute-'))
    with zipfile.ZipFile(BUNDLE) as archive:
        for item in archive.infolist():
            path = (target / item.filename).resolve()
            if not path.is_relative_to(target):
                raise ValueError('Invalid source bundle path')
        archive.extractall(target)
    return target

source = unpack_source(hashlib.sha256(BUNDLE.read_bytes()).hexdigest())
if str(source) not in sys.path:
    sys.path.insert(0, str(source))
runpy.run_path(str(source / 'streamlit_app.py'), run_name='__main__')
