"""
Colorimetry helpers for Fabric Color Variation Detection.

All Lab values in this project are in real CIE L*a*b* units
(L* 0-100, a*/b* roughly -128..127), obtained by converting camera
BGR pixels as sRGB (D65) floats. This matters: OpenCV's 8-bit
BGR->Lab conversion rescales L* to 0-255 and offsets a*/b* by 128,
which silently inflates colour differences. v1 of this project had
that problem; everything here avoids it.

Colour-difference formulas implemented (all vectorised with numpy):
  - CIE76        : Euclidean distance in L*a*b*
  - CIEDE2000    : CIE 142-2001, kL = kC = kH = 1  (primary metric)
  - CMC (l:c)    : BS 6923 / ISO 105-J03, default 2:1 (textile acceptability)

The implementations are checked against the Sharma, Wu & Dalal (2005)
CIEDE2000 test data in tests/verify_colorimetry.py.
"""
import numpy as np
import cv2


def bgr_to_lab(bgr_uint8):
    """uint8 BGR array (..., 3) -> float64 CIE L*a*b* array, same shape."""
    arr = np.asarray(bgr_uint8)
    shape = arr.shape
    f = (arr.reshape(-1, 1, 3).astype(np.float32)) / 255.0
    lab = cv2.cvtColor(f, cv2.COLOR_BGR2Lab)
    return lab.reshape(shape).astype(np.float64)


def lab_to_hex(lab):
    """CIE L*a*b* triple -> '#rrggbb' (for UI swatches only)."""
    arr = np.float32([[list(lab)]])
    bgr = cv2.cvtColor(arr, cv2.COLOR_Lab2BGR)[0][0]
    bgr = np.clip(bgr, 0, 1) * 255
    b, g, r = [int(round(v)) for v in bgr]
    return f"#{r:02x}{g:02x}{b:02x}"


def delta_e_76(lab1, lab2):
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    return np.sqrt(np.sum((lab1 - lab2) ** 2, axis=-1))


def delta_e_2000(lab1, lab2, kL=1.0, kC=1.0, kH=1.0):
    """CIEDE2000 colour difference. lab1 is the reference/standard."""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    L1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    L2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    Cbar = (C1 + C2) / 2.0
    Cbar7 = Cbar ** 7
    G = 0.5 * (1 - np.sqrt(Cbar7 / (Cbar7 + 25.0 ** 7)))
    a1p = (1 + G) * a1
    a2p = (1 + G) * a2
    C1p = np.hypot(a1p, b1)
    C2p = np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360.0
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360.0

    dLp = L2 - L1
    dCp = C2p - C1p
    zero_c = (C1p * C2p) == 0
    dhp = h2p - h1p
    dhp = np.where(dhp > 180, dhp - 360, dhp)
    dhp = np.where(dhp < -180, dhp + 360, dhp)
    dhp = np.where(zero_c, 0.0, dhp)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dhp / 2.0))

    Lbarp = (L1 + L2) / 2.0
    Cbarp = (C1p + C2p) / 2.0
    hsum = h1p + h2p
    habs = np.abs(h1p - h2p)
    hbarp = np.where(
        zero_c, hsum,
        np.where(habs <= 180, hsum / 2.0,
                 np.where(hsum < 360, (hsum + 360) / 2.0, (hsum - 360) / 2.0)))

    T = (1 - 0.17 * np.cos(np.radians(hbarp - 30))
         + 0.24 * np.cos(np.radians(2 * hbarp))
         + 0.32 * np.cos(np.radians(3 * hbarp + 6))
         - 0.20 * np.cos(np.radians(4 * hbarp - 63)))
    dtheta = 30 * np.exp(-(((hbarp - 275) / 25.0) ** 2))
    Cbarp7 = Cbarp ** 7
    RC = 2 * np.sqrt(Cbarp7 / (Cbarp7 + 25.0 ** 7))
    SL = 1 + (0.015 * (Lbarp - 50) ** 2) / np.sqrt(20 + (Lbarp - 50) ** 2)
    SC = 1 + 0.045 * Cbarp
    SH = 1 + 0.015 * Cbarp * T
    RT = -np.sin(np.radians(2 * dtheta)) * RC

    tL = dLp / (kL * SL)
    tC = dCp / (kC * SC)
    tH = dHp / (kH * SH)
    return np.sqrt(tL ** 2 + tC ** 2 + tH ** 2 + RT * tC * tH)


def delta_e_cmc(lab_std, lab_sample, l=2.0, c=1.0):
    """CMC(l:c) colour difference. lab_std is the standard (reference)."""
    s = np.asarray(lab_std, dtype=np.float64)
    t = np.asarray(lab_sample, dtype=np.float64)
    L1, a1, b1 = s[..., 0], s[..., 1], s[..., 2]
    L2, a2, b2 = t[..., 0], t[..., 1], t[..., 2]
    C1 = np.hypot(a1, b1)
    C2 = np.hypot(a2, b2)
    dL = L1 - L2
    dC = C1 - C2
    da = a1 - a2
    db = b1 - b2
    dH = np.sqrt(np.maximum(da ** 2 + db ** 2 - dC ** 2, 0.0))
    SL = np.where(L1 < 16, 0.511, 0.040975 * L1 / (1 + 0.01765 * L1))
    SC = 0.0638 * C1 / (1 + 0.0131 * C1) + 0.638
    C1_4 = C1 ** 4
    F = np.sqrt(C1_4 / (C1_4 + 1900.0))
    H1 = np.degrees(np.arctan2(b1, a1)) % 360.0
    T = np.where((H1 >= 164) & (H1 <= 345),
                 0.56 + np.abs(0.2 * np.cos(np.radians(H1 + 168))),
                 0.36 + np.abs(0.4 * np.cos(np.radians(H1 + 35))))
    SH = SC * (F * T + 1 - F)
    return np.sqrt((dL / (l * SL)) ** 2 + (dC / (c * SC)) ** 2 + (dH / SH) ** 2)