"""
F2 Adaptive Crop Steering — detect each zone's P1 moisture ceiling (Vmax) then:
  A) derive the P2 dryback trigger:  P2 = Vmax * (1 - dryback%)  (EC-stacker still trims around it)
  B) ramp the P1 target up day-over-day toward the detected Vmax.
Pure stdlib. Gated by input_boolean.f2_adaptive_steering_enabled (default OFF). Every setpoint
write is clamped + confidence-gated. Called once per zone per engine cycle from
_update_zone_vwc_capacity via tick(). Nothing runs unless explicitly enabled.
"""
from datetime import datetime, timedelta

_MARGINAL_FRAC = 0.30
_PLATEAU_EPS   = 0.4
_EC_DROP       = 0.4
_CURVE_R2      = 0.90
_CURVE_TOL     = 0.02
_VOTES_NEEDED  = 2
_CLIMB_CAP     = 5.0
_SAMPLE_MIN_DW = 0.05
_MIN_SAMPLES   = 5
_P3_BUFFER     = 3.0   # %VWC kept above the P3 emergency floor so a rate error never triggers an overnight shot


def _num(app, eid, d):
    try:
        return app._get_number_entity_value(eid, d)
    except Exception:
        return d


def _znum(app, z, base, d):
    try:
        return app._get_zone_number(z, base, d)
    except Exception:
        return d


def _sw(app, eid, d):
    try:
        return app._get_switch_state(eid, d)
    except Exception:
        return d


def _enabled(app):
    return _sw(app, 'input_boolean.f2_adaptive_steering_enabled', False)


def _blocked(app, z):
    if _sw(app, 'switch.crop_steering_zone_' + str(z) + '_enabled', True) is False:
        return True
    if _sw(app, 'switch.crop_steering_zone_' + str(z) + '_manual_override', False):
        return True
    if _sw(app, 'input_boolean.f2_flush_mode', False):
        return True
    if _sw(app, 'input_boolean.f2_fill_mode', False):
        return True
    return False


def _st(app, z):
    return app.zone_vwc_capacity.setdefault(z, {})


def tick(app, zone_num, zone_vwc, phase):
    if not _enabled(app):
        return
    if _blocked(app, zone_num):
        return
    _maybe_ramp(app, zone_num)
    ph = getattr(phase, 'name', str(phase or ''))
    today = datetime.now().date().isoformat()
    if 'P1' in ph:
        _st(app, zone_num)['ad_in_p3'] = False
        _detect(app, zone_num, zone_vwc)
    else:
        st = _st(app, zone_num)
        if st.get('ad_samples') and st.get('ad_locked_date') != today:
            _lock(app, zone_num, 'p1_exit')
        st['ad_samples'] = []
        if 'P3' in ph:
            _track_p3(app, zone_num, zone_vwc)
        else:
            st['ad_in_p3'] = False


def _detect(app, zone_num, vwc):
    if vwc is None:
        return
    st = _st(app, zone_num)
    today = datetime.now().date().isoformat()
    if st.get('ad_day') != today:
        st['ad_day'] = today
        st['ad_samples'] = []
        st['ad_ecmax'] = None
        st['ad_locked_date'] = None
        st['ad_umax'] = 0.0
    cw = _num(app, 'sensor.crop_steering_zone_' + str(zone_num) + '_daily_water_usage', 0.0)
    ec = _num(app, 'sensor.crop_steering_zone_' + str(zone_num) + '_ec', -1.0)
    samples = st.setdefault('ad_samples', [])
    if (not samples) or (cw - samples[-1][0]) >= _SAMPLE_MIN_DW or vwc > samples[-1][1] + 0.3:
        samples.append((cw, vwc))
        if len(samples) > 200:
            del samples[0:len(samples) - 200]
    if ec is not None and ec >= 0:
        st['ad_ecmax'] = ec if st.get('ad_ecmax') is None else max(st['ad_ecmax'], ec)
    vmax, conf, votes = _evaluate(app, zone_num, st, vwc, ec)
    _publish(app, zone_num, vmax, conf, votes, st.get('ad_locked_date') == today)
    if st.get('ad_locked_date') == today:
        return
    conf_min = _num(app, 'input_number.f2_vmax_confidence_min', 0.6)
    if votes >= _VOTES_NEEDED and conf >= conf_min and len(samples) >= _MIN_SAMPLES:
        _lock(app, zone_num, 'voted', vmax, conf)


def _evaluate(app, zone_num, st, vwc, ec):
    samples = st.get('ad_samples', [])
    if len(samples) < _MIN_SAMPLES:
        peak = max((v for _, v in samples), default=(vwc if vwc is not None else 0.0))
        return (round(peak, 1), 0.0, 0)
    ws = [w for w, _ in samples]
    vs = [v for _, v in samples]
    votes = 0
    signals = 0

    def slope(i0, i1):
        dw = ws[i1] - ws[i0]
        return (vs[i1] - vs[i0]) / dw if dw > 1e-6 else 0.0

    # 1 - marginal-uptake collapse
    signals += 1
    recent = slope(max(0, len(vs) - 3), len(vs) - 1)
    mx = 0.0
    for k in range(1, len(vs)):
        s = slope(k - 1, k)
        if s > mx:
            mx = s
    st['ad_umax'] = max(st.get('ad_umax', 0.0), mx)
    if st['ad_umax'] > 1e-6 and recent < _MARGINAL_FRAC * st['ad_umax']:
        votes += 1
    # 2 - peak plateau
    signals += 1
    if len(vs) >= 6 and (max(vs[-3:]) - max(vs[-6:-3])) < _PLATEAU_EPS:
        votes += 1
    # 3 - EC runoff
    signals += 1
    if ec is not None and ec >= 0 and st.get('ad_ecmax') is not None and ec < st['ad_ecmax'] - _EC_DROP:
        votes += 1
    # 4 - saturation-curve asymptote
    signals += 1
    vmax_fit, r2 = _fit_vmax(ws, vs)
    if vmax_fit is not None and r2 >= _CURVE_R2 and vwc is not None and vwc >= (1.0 - _CURVE_TOL) * vmax_fit:
        votes += 1
    peak = max(vs)
    vmax = vmax_fit if (vmax_fit is not None and r2 >= _CURVE_R2 and vmax_fit >= peak) else peak
    cur_max = st.get('current_max')
    if cur_max:
        vmax = min(vmax, float(cur_max) + _CLIMB_CAP)
        vmax = max(vmax, float(cur_max) * 0.9)
    conf = votes / float(signals) if signals else 0.0
    return (round(vmax, 1), round(conf, 2), votes)


def _fit_vmax(ws, vs):
    n = len(ws)
    if n < 5:
        return (None, 0.0)
    try:
        Sw = sum(ws)
        Sw2 = sum(w * w for w in ws)
        Sw3 = sum(w ** 3 for w in ws)
        Sw4 = sum(w ** 4 for w in ws)
        Sv = sum(vs)
        Swv = sum(w * v for w, v in zip(ws, vs))
        Sw2v = sum(w * w * v for w, v in zip(ws, vs))
        a, b, c = _solve3([[Sw4, Sw3, Sw2], [Sw3, Sw2, Sw], [Sw2, Sw, n]], [Sw2v, Swv, Sv])
        if a is None or a >= 0:
            return (None, 0.0)
        wv = -b / (2 * a)
        vmax = a * wv * wv + b * wv + c
        mean = Sv / n
        ss_tot = sum((v - mean) ** 2 for v in vs)
        ss_res = sum((v - (a * w * w + b * w + c)) ** 2 for w, v in zip(ws, vs))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
        if vmax < max(vs) or vmax > max(vs) + 15:
            return (None, r2)
        return (vmax, r2)
    except Exception:
        return (None, 0.0)


def _solve3(A, B):
    M = [A[i][:] + [B[i]] for i in range(3)]
    for i in range(3):
        p = M[i][i]
        if abs(p) < 1e-12:
            return (None, None, None)
        for j in range(i, 4):
            M[i][j] /= p
        for k in range(3):
            if k != i:
                f = M[k][i]
                for j in range(i, 4):
                    M[k][j] -= f * M[i][j]
    return (M[0][3], M[1][3], M[2][3])


def _lock(app, zone_num, reason, vmax=None, conf=None):
    st = _st(app, zone_num)
    today = datetime.now().date().isoformat()
    if vmax is None:
        vmax, conf, _ = _evaluate(app, zone_num, st, None, None)
    st['ad_vmax'] = vmax
    st['ad_conf'] = conf
    st['ad_locked_date'] = today
    app.log('Zone ' + str(zone_num) + ': P1 Vmax locked at ' + str(vmax) + '% (conf ' + str(conf) + ', ' + reason + ')', level='INFO')
    _apply_p2(app, zone_num, vmax)
    _publish(app, zone_num, vmax, conf, None, True)


def _apply_p2(app, zone_num, vmax):
    if vmax is None or vmax <= 0:
        return
    veg = False
    try:
        veg = app._zone_is_vegetative(zone_num)
    except Exception:
        pass
    db = _znum(app, zone_num, 'number.crop_steering_vegetative_dryback_target' if veg else 'number.crop_steering_generative_dryback_target', 20.0 if veg else 30.0)
    base = vmax * (1.0 - db / 100.0)
    floor = _znum(app, zone_num, 'number.crop_steering_p3_emergency_vwc_threshold', 30.0) + 3.0
    p1t = _znum(app, zone_num, 'number.crop_steering_p1_target_vwc', vmax)
    ceil = min(p1t, vmax) - 1.0
    newp2 = round(min(max(base, floor), ceil), 1)
    eid = 'number.crop_steering_zone_' + str(zone_num) + '_p2_vwc_threshold'
    try:
        app.call_service('number/set_value', entity_id=eid, value=newp2)
        app.log('Zone ' + str(zone_num) + ': dryback-derived P2 base = ' + str(newp2) + '% (Vmax ' + str(round(vmax, 1)) + ' x (1-' + str(int(db)) + '%), clamp[' + str(round(floor)) + ',' + str(round(ceil)) + ']). EC-stack trims from here.', level='INFO')
    except Exception as e:
        app.log('Zone ' + str(zone_num) + ': P2 set failed: ' + str(e), level='ERROR')


def _maybe_ramp(app, zone_num):
    st = _st(app, zone_num)
    today = datetime.now().date().isoformat()
    if st.get('ad_ramp_date') == today:
        return
    st['ad_ramp_date'] = today
    vmax = st.get('ad_vmax')   # ramp ONLY off a real detected Vmax, never the raw (often over-sat) current_max
    if not vmax:
        return
    climb = _num(app, 'input_number.f2_p1_climb_rate_per_day', 1.0)
    margin = _num(app, 'input_number.f2_p1_margin', 2.0)
    fc = _num(app, 'number.crop_steering_field_capacity', 60.0)
    eid = 'number.crop_steering_zone_' + str(zone_num) + '_p1_target_vwc'
    cur = _num(app, eid, -1.0)
    if cur < 0:
        return
    ceiling = min(float(vmax), fc) - margin   # P1 never targets above field capacity
    newp1 = round(min(cur + climb, ceiling), 1)
    if newp1 > cur + 0.05:
        try:
            app.call_service('number/set_value', entity_id=eid, value=newp1)
            app.log('Zone ' + str(zone_num) + ': P1 target ramped ' + str(cur) + '->' + str(newp1) + '% (+' + str(climb) + '/day, cap Vmax ' + str(round(float(vmax), 1)) + '-' + str(int(margin)) + ')', level='INFO')
        except Exception as e:
            app.log('Zone ' + str(zone_num) + ': P1 ramp failed: ' + str(e), level='ERROR')


def _publish(app, zone_num, vmax, conf, votes, locked):
    try:
        app.set_state('sensor.crop_steering_zone_' + str(zone_num) + '_vmax_detected',
                      state=(round(float(vmax), 1) if vmax is not None else 'unknown'),
                      attributes={'confidence': conf, 'votes': votes, 'locked_today': bool(locked),
                                  'friendly_name': 'Zone ' + str(zone_num) + ' Detected Vmax',
                                  'unit_of_measurement': '%', 'icon': 'mdi:water-plus'})
    except Exception:
        pass


# ---------------- predictive P3 overnight dryback ----------------

def _hours_to_lights_on(app):
    on = int(_num(app, 'number.crop_steering_lights_on_hour', 10))
    now = datetime.now()
    target = now.replace(hour=max(0, min(23, on)), minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds() / 3600.0


def _track_p3(app, zone_num, vwc):
    """Measure this zone's realised overnight dryback rate (%VWC/hour) and publish a lights-on prediction."""
    if vwc is None:
        return
    st = _st(app, zone_num)
    now = datetime.now()
    if not st.get('ad_in_p3'):
        st['ad_in_p3'] = True
        st['ad_p3_peak'] = vwc
        st['ad_p3_start'] = now.isoformat()
        _publish_p3(app, zone_num, vwc)
        return
    if vwc > st.get('ad_p3_peak', vwc):
        st['ad_p3_peak'] = vwc
    try:
        start = datetime.fromisoformat(st.get('ad_p3_start'))
    except Exception:
        st['ad_p3_start'] = now.isoformat()
        return
    hrs = (now - start).total_seconds() / 3600.0
    drop = float(st.get('ad_p3_peak', vwc)) - vwc
    if hrs >= 1.0 and drop >= 1.0:
        r = drop / hrs
        prev = st.get('ad_dryback_rate')
        st['ad_dryback_rate'] = round(r if prev is None else 0.4 * r + 0.6 * float(prev), 3)
    _publish_p3(app, zone_num, vwc)


def get_zone_rate(app, zone_num):
    """Per-zone overnight dryback rate (%VWC/hour). None unless adaptive is on and a rate is learned.
    Consumed by the engine's _get_zone_dryback_rate so its existing P3 timing becomes per-zone."""
    if not _enabled(app):
        return None
    r = _st(app, zone_num).get('ad_dryback_rate')
    return float(r) if r else None


def safe_target_dryback(app, zone_num, vwc):
    """Max % dryback that still lands lights-on VWC at/above (P3 emergency floor + buffer).
    The engine caps its target_dryback at this -> no overnight emergency shots. None unless adaptive on."""
    if not _enabled(app) or vwc is None or vwc <= 0:
        return None
    floor = _znum(app, zone_num, 'number.crop_steering_p3_emergency_vwc_threshold', 30.0) + _P3_BUFFER
    if vwc <= floor:
        return 0.0
    return round((vwc - floor) / vwc * 100.0, 1)


def _publish_p3(app, zone_num, vwc):
    try:
        st = _st(app, zone_num)
        r = st.get('ad_dryback_rate')
        hrs = _hours_to_lights_on(app)
        pred = round(vwc - float(r) * hrs, 1) if (r and vwc is not None) else None
        floor = _znum(app, zone_num, 'number.crop_steering_p3_emergency_vwc_threshold', 30.0) + _P3_BUFFER
        app.set_state('sensor.crop_steering_zone_' + str(zone_num) + '_p3_prediction',
                      state=(pred if pred is not None else 'unknown'),
                      attributes={'rate_pct_per_h': (round(float(r), 2) if r else None),
                                  'hours_to_lights_on': round(hrs, 1),
                                  'current_vwc': (round(float(vwc), 1) if vwc is not None else None),
                                  'p3_floor_plus_buffer': round(floor, 1),
                                  'will_hit_floor': bool(pred is not None and pred < floor),
                                  'friendly_name': 'Zone ' + str(zone_num) + ' P3 lights-on VWC (predicted)',
                                  'unit_of_measurement': '%', 'icon': 'mdi:weather-night'})
    except Exception:
        pass
