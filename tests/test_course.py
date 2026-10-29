import pytest
from investlab import profile,portfolio,research,store
def answers(value=3):return {q[0]:value for q in profile.QUESTIONS}
def test_profile_redlines_override_high_score():
    a=answers();a['loss']=0
    assert profile.assess(a)['equity_cap']==0
    a=answers();a['experience']=0
    assert profile.assess(a)['level']==2
def test_profile_input_and_disclosure():
    with pytest.raises(ValueError):profile.assess({})
    a=answers();a['debt']=True
    with pytest.raises(ValueError):profile.assess(a)
    with pytest.raises(ValueError):profile.save({'answers':answers()})
def test_horizon_mismatch_and_expiry(monkeypatch):
    p=profile.assess(answers());p['answers']['liquidity']=1;p['expired']=False
    monkeypatch.setattr(profile,'current',lambda:p)
    assert profile.policy('short')['equity_cap']>.0
    assert profile.policy('long')['equity_cap']==0
    p['expired']=True
    assert profile.policy()['equity_cap']==0
    with pytest.raises(ValueError):profile.policy('forever')
def test_profile_is_reference_for_manual_budget(monkeypatch):
    monkeypatch.setattr(profile,'current',lambda:None)
    assert profile.policy()['equity_cap']==0

def test_education_validation():
    with pytest.raises(ValueError):research.quiz([])
