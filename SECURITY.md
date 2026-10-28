# Güvenlik politikası

## Desteklenen sürümler

Güvenlik düzeltmeleri yalnızca **en son sürüme** yapılır. Lütfen her zaman [son sürümü](https://github.com/ErkulOfluoglu/devre-analizi/releases/latest) kullanın.

## Güvenlik açığı nasıl bildirilir?

Programda bir güvenlik açığı bulduğunuzu düşünüyorsanız lütfen **herkese açık Issues sayfasına yazmayın**. Bunun yerine özel bildirim kanalını kullanın:

1. Deponun **[Security](https://github.com/ErkulOfluoglu/devre-analizi/security)** sekmesine gidin.
2. **Report a vulnerability** düğmesine basın (doğrudan bağlantı: [yeni güvenlik bildirimi](https://github.com/ErkulOfluoglu/devre-analizi/security/advisories/new)).
3. Sorunu, nasıl tekrarlanabileceğini ve etkilenen sürümü yazın. Varsa örnek bir `.devre` dosyası eklemek çok yardımcı olur.

Bildiriminizi yalnızca siz ve geliştirici görür. Bildirim alındıktan sonra en kısa sürede dönüş yapılır; sorun doğrulanırsa düzeltilmiş bir sürüm yayınlanır ve isterseniz adınız sürüm notlarında teşekkürle anılır.

## Kapsam

Devre Analizi internete bağlanmaz, hesap açtırmaz ve kişisel veri toplamaz. Yine de şu tür sorunları bildirmeniz değerlidir:

- Hazırlanmış bir `.devre` dosyasını açınca programın beklenmedik bir şey yapması (kod çalıştırma, dosya yazma vb.),
- Programın kendi başlattığı yerel çözücü sunucusunun (yalnızca `127.0.0.1`) bilgisayar dışından erişilebilir olması,
- Kurulum paketiyle ilgili sorunlar.

Yanlış hesaplanmış bir sonuç ya da başka bir hata güvenlik açığı değildir; onları [Issues](https://github.com/ErkulOfluoglu/devre-analizi/issues) sayfasından bildirebilirsiniz.

---

*English:* To report a security vulnerability, please use GitHub's [private vulnerability reporting](https://github.com/ErkulOfluoglu/devre-analizi/security/advisories/new) instead of opening a public issue. Only the latest release receives security fixes.
