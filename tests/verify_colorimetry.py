"""Verify colorimetry.py against published CIEDE2000 test data
(Sharma, Wu & Dalal 2005) and against colour-science for CMC.
Run:  python tests/verify_colorimetry.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from colorimetry import delta_e_2000, delta_e_cmc, bgr_to_lab

# (L1,a1,b1, L2,a2,b2, expected dE00) — Sharma et al. 2005, Table 1
SHARMA = [
    (50.0000, 2.6772, -79.7751, 50.0000, 0.0000, -82.7485, 2.0425),
    (50.0000, 3.1571, -77.2803, 50.0000, 0.0000, -82.7485, 2.8615),
    (50.0000, 2.8361, -74.0200, 50.0000, 0.0000, -82.7485, 3.4412),
    (50.0000, -1.3802, -84.2814, 50.0000, 0.0000, -82.7485, 1.0000),
    (50.0000, 0.0000, 0.0000, 50.0000, -1.0000, 2.0000, 2.3669),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0009, 7.1792),
    (50.0000, 2.4900, -0.0010, 50.0000, -2.4900, 0.0011, 7.2195),
    (50.0000, -0.0010, 2.4900, 50.0000, 0.0009, -2.4900, 4.8045),
    (50.0000, 2.5000, 0.0000, 73.0000, 25.0000, -18.0000, 27.1492),
    (50.0000, 2.5000, 0.0000, 50.0000, 3.2592, 0.3350, 1.0000),
    (60.2574, -34.0099, 36.2677, 60.4626, -34.1751, 39.4387, 1.2644),
    (22.7233, 20.0904, -46.6940, 23.0331, 14.9730, -42.5619, 2.0373),
    (90.8027, -2.0831, 1.4410, 91.1528, -1.6435, 0.0447, 1.4441),
    (2.0776, 0.0795, -1.1350, 0.9033, -0.0636, -0.5514, 0.9082),
]

def main():
    d = np.array(SHARMA)
    got = delta_e_2000(d[:, 0:3], d[:, 3:6])
    err = np.abs(got - d[:, 6]).max()
    print(f"CIEDE2000 vs Sharma et al. (n={len(d)}): max abs error = {err:.5f}")
    assert err < 1e-4, "CIEDE2000 mismatch"

    try:
        import colour
        rng = np.random.default_rng(1)
        a = np.column_stack([rng.uniform(5, 95, 500), rng.uniform(-80, 80, 500), rng.uniform(-80, 80, 500)])
        b = a + rng.normal(0, 4, a.shape)
        ref = colour.delta_E(a, b, method="CMC", l=2, c=1)
        mine = delta_e_cmc(a, b, 2, 1)
        print(f"CMC(2:1) vs colour-science (n=500): max abs error = {np.abs(ref-mine).max():.6f}")
        ref00 = colour.delta_E(a, b, method="CIE 2000")
        print(f"CIEDE2000 vs colour-science (n=500): max abs error = {np.abs(ref00-delta_e_2000(a,b)).max():.6f}")
    except ImportError:
        print("colour-science not installed; CMC cross-check skipped")

    white = bgr_to_lab(np.uint8([[255, 255, 255]]))[0]
    print("sRGB white ->", np.round(white, 3), "(expected ~[100, 0, 0])")
    assert abs(white[0] - 100) < 0.1
    print("All colorimetry checks passed.")

if __name__ == "__main__":
    main()