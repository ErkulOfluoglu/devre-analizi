"""
Paketlenmiş çözücünün giriş noktası.

Kurulum paketinde Python kurulu olmayabilir; PyInstaller bu dosyadan
backend\\CircuitAnalyzerAPI.exe üretir. WPF uygulaması (BackendManager)
onu boş bir portla başlatır:

    CircuitAnalyzerAPI.exe --port 8123

Geliştirme sırasında da çalışır:  python run_server.py --port 8000
"""

import argparse
import multiprocessing


def main() -> None:
    parser = argparse.ArgumentParser(description="Devre Analizi çözücüsü")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()

    # Ağır içe aktarmalar argümanlar okunduktan sonra (--help hızlı kalsın)
    import uvicorn
    from main import app

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
