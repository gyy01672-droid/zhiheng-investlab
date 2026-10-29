"""Set isolation before pytest imports any application module."""
import os,tempfile
from pathlib import Path
import pytest
root=Path(__file__).resolve().parents[1]/'tmp'/'test-states'
root.mkdir(parents=True,exist_ok=True)
test_state=Path(tempfile.mkdtemp(prefix='isolated-',dir=root)).resolve()
os.environ['INVESTLAB_STATE']=str(test_state)
from investlab.config import STATE
if STATE!=test_state:raise RuntimeError('Refusing tests against a non-test database')
from investlab import store
@pytest.fixture(autouse=True)
def isolated_database():
    store.init()
    with store.db() as c:
        for table in ['lots','trades','events','settings','scans']:c.execute('DELETE FROM '+table)
