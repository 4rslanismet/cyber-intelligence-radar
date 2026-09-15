"""Google Drive OAuth - bir kerelik kurulum script'i.

Kullanım (sunucuda):
    source .venv/bin/activate
    python3 -m src.gdrive_auth

Önkoşul: .env içinde GDRIVE_OAUTH_CLIENT_ID ve GDRIVE_OAUTH_CLIENT_SECRET
dolu olmalı (Google Cloud Console > Credentials > OAuth client ID > tür:
"TVs and Limited Input devices"). README'deki "Google Drive kurulumu"
bölümüne bakın.

Script bir doğrulama URL'si + kod basar. Bu kodu HERHANGİ bir cihazda
(telefon, laptop - sunucuda tarayıcı olmasına gerek yok) o adrese girip
onaylarsınız; script arka planda bekleyip token'ı data/.gdrive_token.json
içine kaydeder. Bundan sonra pipeline hiçbir insan etkileşimi olmadan
otomatik senkron yapar.
"""
from __future__ import annotations

from . import config, gdrive


def main() -> None:
    if not config.GDRIVE_OAUTH_CLIENT_ID or not config.GDRIVE_OAUTH_CLIENT_SECRET:
        print(
            "Önce .env içine GDRIVE_OAUTH_CLIENT_ID ve GDRIVE_OAUTH_CLIENT_SECRET "
            "değerlerini girin (Google Cloud Console'dan alınır), sonra tekrar çalıştırın."
        )
        return

    info = gdrive.start_device_auth()
    print("\n== Google Drive yetkilendirme ==")
    print(f"1) Şu adrese gidin:  {info['verification_url']}")
    print(f"2) Şu kodu girin:    {info['user_code']}")
    print("\nOnaylayınca burada otomatik devam edecek, bekleniyor...\n")

    gdrive.poll_device_token(info["device_code"], info["interval"], info["expires_in"])

    print("✅ Bağlantı kuruldu. Token data/.gdrive_token.json içinde saklandı.")
    print("   GDRIVE_ENABLED=true yapıp .env'i kaydetmeyi unutmayın.")

    if not config.GDRIVE_ROOT_FOLDER_ID:
        root_id = gdrive.ensure_folder(config.GDRIVE_ROOT_FOLDER_NAME)
        print(f'   Drive kök klasörü "{config.GDRIVE_ROOT_FOLDER_NAME}" oluşturuldu/bulundu, ID: {root_id}')
        print("   İsterseniz bu ID'yi .env içinde GDRIVE_ROOT_FOLDER_ID olarak sabitleyebilirsiniz.")


if __name__ == "__main__":
    main()
