# LinkedIn Gönderisi (TR) — Taslak

*Sadece taslak — henüz yayınlanmadı. Paylaşmadan önce gözden geçirin/
düzenleyin; birinci ağızdan (maintainer'ın kendi sesiyle) yazıldı.*

---

Her gün onlarca güvenlik kaynağını ve akademik makaleyi takip ederken
hep aynı sorunla karşılaşıyordum: okuduklarımın çoğu aslında yeni
değildi — aynı olay, başka bir kaynaktan tekrar geliyordu, ya da zaten
dünkü brifingimde vardı.

Bu yüzden Cyber Intelligence Radar'ı farklı bir soru üzerine kurdum.
"Bu yeni mi?" değil — **"gerçekten ne değişti?"**

Aynı olayı (bir CVE, bir olay) birden fazla çalıştırma boyunca takip
ediyor ve sadece gerçekten önemli bir şey değiştiğinde tekrar
yüzeye çıkarıyor: KEV listesine eklenme, aktif istismar teyidi, yeni
bir IOC, bir düzeltmenin yayınlanması. Bir kaynağın aynı içeriği tekrar
yayınlaması tetiklemiyor — gerçek bir değişiklik tetikliyor.

Aynı mantığı akademik makaleler için de uyguluyor: arama motoru değil,
profil bazlı ilgi skorlamasından beslenen küçük, seçilmiş bir okuma
listesi. Ve ürettiği her yapılandırılmış iddia (CVE ID, IOC, CWE
eşlemesi) brifinge girmeden önce kaynak metinle mekanik olarak
doğrulanıyor — "modele güven" değil, kanıt öncelikli.

Self-hosted, açık kaynak (Apache-2.0), ve tüm pipeline `pip install -e .`
+ `cyber-radar demo` kadar yakın — tam bir örnek brifing görmek için
API anahtarı ya da ağ bağlantısı bile gerekmiyor.

Repo: https://github.com/4rslanismet/cyber-intelligence-radar

Geri bildirime gerçekten açığım — özellikle material-update tespit
mantığı hakkında, ki bu projede en gurur duyduğum kısım.

#cybersecurity #threatintelligence #opensource #python #selfhosted
