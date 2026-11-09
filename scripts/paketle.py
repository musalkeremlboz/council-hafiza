"""Sürüm paketini hazırlar: dist/council-hafiza-X.Y.Z.zip (kur.py, kur.md, bağımlılık kilitleri, tekerlek, lisans) ve dist/SHA256SUMS.txt."""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

KOK = Path(__file__).resolve().parents[1]
DIST = KOK / "dist"


def main() -> None:
    DIST.mkdir(exist_ok=True)
    for p in DIST.glob("*"):
        p.unlink()
    subprocess.run([sys.executable, "-m", "pip", "wheel", str(KOK), "-w", str(DIST), "--no-deps", "-q"], check=True)
    teker = next(DIST.glob("council_hafiza-*.whl"))
    surum = teker.name.split("-")[1]
    zp = DIST / f"council-hafiza-{surum}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for ad in ("kur.py", "kur.md", "kilit.txt", "kilit-vektor.txt", "LICENSE", "NOTICE"):
            z.write(KOK / ad, ad)
        z.write(teker, teker.name)
    satirlar = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}" for p in (zp, teker)]
    (DIST / "SHA256SUMS.txt").write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    print("\n".join(satirlar))


if __name__ == "__main__":
    main()
