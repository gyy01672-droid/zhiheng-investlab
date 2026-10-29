import pytest
import numpy as np
from investlab import portfolio

def candidates():
    return [{'code':str(i),'quote':{'name':'test','price':3+i*.5,'industry':'test','quote_time':'test'}} for i in range(10)]

def test_ten_thousand_fills_investment_target():
    rows,cash=portfolio.fill_lots(candidates(),np.repeat(.085,10),10000,8500)
    assert 8200<10000-cash<=8500
    assert all(r['quantity']%100==0 for r in rows)

def test_small_account_does_not_require_four_stocks():
    rows,cash=portfolio.fill_lots(candidates(),np.repeat(.085,10),600,510)
    assert rows and cash>=90 and 510-(600-cash)<300.3

def test_manual_budget_and_lots(monkeypatch):
    monkeypatch.setattr(portfolio.market,'quote',lambda c:{'name':c,'price':10,'industry':'test','quote_time':'test','stale':False})
    with pytest.raises(ValueError):portfolio.manual(1000,[{'code':'600900','quantity':100}])
    with pytest.raises(ValueError):portfolio.manual(2000,[{'code':'600900','quantity':101}])
    r=portfolio.manual(2000,[{'code':'600900','quantity':100}])
    assert r['spent']==1001 and r['cash']==999
