---
version: 1
name: Devre Analizi
description: Windows 11 Fluent zemin, devrenin üstünde yüzen cam kontroller, Notion sakinliğinde bir okuma paneli ve gerçek akımı izleyen bir akım ışığı.

colors:
  light:
    mica: "#F3F3F3"            # pencere zemini (programda Windows Mica)
    layer: "#FFFFFF8C"         # tuval katmanı, %55 beyaz
    layer-edge: "#0000000F"
    canvas-dot: "#37352F29"
    glass-base: "#FAFAFA"      # camın opak tabanı (altındaki devre net görünmesin)
    acrylic: "#FCFCFC8C"       # açılan eleman listesi
    glass: "#FFFFFF66"         # yüzen araç çubuğu, eleman kartı
    glass-edge: "#FFFFFFE6"
    glass-divider: "#00000014"
    paper: "#FFFFFF"           # okuma paneli
    paper-soft: "#F6F5F4"      # kod ve denklem blokları
    hairline: "#EBEAE8"
    control: "#FFFFFFB3"
    control-edge: "#00000014"
    ink: "#1F1E1C"
    ink-body: "#31302E"
    ink-muted: "#615D59"
    ink-faint: "#716C66"
    wire: "#37352F"
    accent: "#0071E3"
    on-accent: "#FFFFFF"
  dark:
    mica: "#202020"
    layer: "#3A3A3A4D"
    layer-edge: "#FFFFFF12"
    canvas-dot: "#FFFFFF1A"
    glass-base: "#262626"
    acrylic: "#2C2C2C8C"
    glass: "#34343866"
    glass-edge: "#FFFFFF29"
    glass-divider: "#FFFFFF1A"
    paper: "#272727"
    paper-soft: "#202020"
    hairline: "#FFFFFF14"
    control: "#FFFFFF0F"
    control-edge: "#FFFFFF17"
    ink: "#F3F2EF"
    ink-body: "#F3F2EFDB"
    ink-muted: "#F3F2EF9E"
    ink-faint: "#F3F2EF8C"
    wire: "#CFCDC6"
    accent: "#5AA9FF"
    on-accent: "#0A1A2F"

typography:
  font-ui: "Segoe UI Variable Text, Segoe UI"
  font-display: "Segoe UI Variable Display, Segoe UI"
  font-mono: "Cascadia Mono, Consolas"
  caption: { size: 12, weight: 400 }
  label: { size: 12, weight: 600 }
  body: { size: 14, weight: 400 }
  body-strong: { size: 14, weight: 600 }
  reading: { size: 15, weight: 400, lineHeight: 24 }
  reading-h2: { size: 17, weight: 700, lineHeight: 24 }
  reading-h1: { size: 22, weight: 700, lineHeight: 28 }
  mono: { size: 13, weight: 400, lineHeight: 21 }

rounded:
  control: 6     # düğme, açılır kutu, şerit öğesi
  card: 8        # tuval katmanı, okuma paneli, kod bloğu
  flyout: 12     # açılan eleman listesi
  glass: 14      # eleman kartı
  toolbar: 16    # yüzen araç çubuğu

spacing: [4, 8, 12, 16, 20, 24, 28]
---

# Devre Analizi tasarım kuralları

Bu dosya arayüzün nasıl görüneceğini anlatır. Arayüze bir şey eklerken ya da değiştirirken önce burası okunur. Onaylanan taslak "D: Not Defteri + Cam" (2026-11-02).

## Genel bakış

Program bir defter gibi sakin durur; devre ve çözüm metni öne çıkar, düğmeler geri çekilir. Pencere Windows 11'in Fluent dilini konuşur. Devrenin üstünde yüzen birkaç kontrol camdandır ve altındaki devre bulanık görünür. Çözümün okunduğu sağ panel camsız, düz bir kâğıttır. Tek vurgu rengi mavidir: Çöz düğmesi, seçili şeyin işareti ve akım ışığı. Başka hiçbir şey mavi olmaz.

## Katmanlar

Ekran dört katmandan oluşur. Aşağıdan yukarı:

1. **Zemin (mica).** Pencerenin tamamı. Programda Windows 11'in Mica malzemesi, duvar kâğıdının rengini çok hafif alır. Başlık çubuğu ve sol şerit doğrudan bu zeminin üstündedir, kendi arka planları yoktur.
2. **İçerik katmanları (layer, paper).** Tuval ve okuma paneli. İkisi ayrı kartlardır, aralarında 8 px boşluk vardır, köşeleri 8 px yuvarlaktır. Tuval yarı saydamdır (zemin hafifçe görünür) ve 20 px'lik nokta ızgarası taşır. Okuma paneli tamamen opaktır.
3. **Cam (acrylic, glass).** Yalnız tuvalin üstünde yüzen parçalar: açılan eleman listesi, alttaki araç çubuğu, seçili eleman kartı.
4. **Açılır pencereler.** Menüler, iletişim kutuları. Fluent'in kendi açılır stilini kullanır.

## Renkler

Yukarıdaki değerler taslaktan alınmıştır. Programdaki karşılıkları şöyle eşlenir (eski anahtar adları korunur, değerleri değişir):

| Görev | Açık | Koyu | WPF anahtarı |
|---|---|---|---|
| Pencere zemini | #F3F3F3 | #202020 | `Brush.Bg.Window` (Mica açıksa saydam) |
| Tuval | %55 beyaz | %30 #3A3A3A | `Brush.Canvas.Bg` |
| Izgara noktası | #37352F %16 | beyaz %10 | `Brush.Canvas.Grid` |
| Okuma paneli | #FFFFFF | #272727 | `Brush.Bg.Surface` |
| Kod/denklem bloğu | #F6F5F4 | #202020 | `Brush.Bg.SurfaceAlt` |
| İnce çizgi | #EBEAE8 | beyaz %8 | `Brush.Border.Default` |
| Başlık yazısı | #1F1E1C | #F3F2EF | `Brush.Text.Primary` |
| Gövde yazısı | #31302E | #F3F2EF %86 | `Brush.Text.Body` |
| İkincil yazı | #615D59 | #F3F2EF %62 | `Brush.Text.Secondary` |
| Soluk yazı | #716C66 | #F3F2EF %55 | `Brush.Text.Tertiary` |
| Tel | #37352F | #CFCDC6 | `Brush.Circuit.Wire` |
| Vurgu | #0071E3 | #5AA9FF | `Brush.Accent`, `Brush.Overlay.Current` |

Kurallar:
- Mavi yalnız eylem (Çöz), seçim işareti ve akım ışığı içindir. Süs için kullanılmaz.
- Başarı, uyarı ve hata renkleri (`Brush.Success`, `Warning`, `Error`) olduğu gibi kalır ve yalnız durum bildirir.
- Yazı renkleri sıcak gri tonlardır (Notion'daki gibi), saf siyah kullanılmaz.
- Camın üstüne mavi yazı konmaz; okunması zorlaşır.
- Her yazı arka planına karşı en az 4,5:1 karşıtlık taşır. Soluk yazı (#716C66) beyaz ve paper-soft üstünde 4,7:1 ile en düşük tondur, yalnız küçük etiketlerde kullanılır.

## Yazı

Tek aile: Segoe UI Variable. Başlıklarda Display, geri kalan her yerde Text kesimi. Sayılar ve denklemler Cascadia Mono.

- Arayüz (düğmeler, şerit, menüler): 14 px normal, küçük etiketler 12 px.
- Okuma paneli: gövde 15 px, satır yüksekliği 24 px. Başlık 22 px kalın, alt başlık 17 px kalın. Adım etiketi ("ADIM 1 / 4") 12 px yarı kalın, soluk renkte.
- Kalın ile normal arasındaki fark hiyerarşiyi taşır; gövde yazısı hiçbir zaman kalın olmaz.
- Değer sütunlarında rakamlar eşit genişlikte olur (tabular rakamlar), böylece alt alta hizalanır.
- WPF'de satır yüksekliği `LineHeight` ve `LineStackingStrategy="BlockLineHeight"` ile verilir.

## Şekil ve boşluk

- Köşe yarıçapları: kontroller 6, kartlar 8, açılan liste 12, eleman kartı 14, araç çubuğu 16. Cam ne kadar yüzerse köşesi o kadar yuvarlaktır.
- Boşluklar 4'ün katlarıdır: 4, 8, 12, 16, 20, 24, 28.
- Okuma panelinin iç kenar boşluğu 28–30 px, paragraf arası 10 px, bölüm arası 26 px.
- Sağ panel varsayılan 460 px genişliğindedir (kullanıcı ayırıcıyla 360–900 px arasında ayarlar); sol şerit 72 px. Kartlar arası boşluk 8 px.

## Cam kuralları

Cam yalnız içeriğin üstünde yüzen, geçici ya da küçük kontrollerde kullanılır. Microsoft'un Acrylic yönergesi ve Apple'ın Liquid Glass yaklaşımı aynı şeyi söyler: cam kontrol katmanına aittir, içeriğe değil.

Camın olduğu yerler:
- **Açılan eleman listesi** (acrylic, bulanıklık 30): kategoriye tıklayınca tuvalin sol üstünde açılır.
- **Araç çubuğu** (glass, bulanıklık 24): tuvalin alt ortasında yüzer.
- **Eleman kartı** (glass, bulanıklık 22): seçili elemanın yanında açılır.

Camın olmadığı yerler:
- Okuma paneli: uzun metin camın üstünde yorar.
- Sol şerit ve başlık çubuğu: zeminin üstünde dururlar. İki cam yan yana gelirse arada çirkin bir ek yeri oluşur.
- Cam camın üstüne binmez.

Camın tarifi: opak bir taban, onun üstünde arkasındaki tuvalin bulanık kopyası, üstünde yarı saydam renk, 1 px açık kenar, üst kenarda ince bir parlak çizgi ve yumuşak gölge. Gölge tek katmanlı ve hafiftir (açıkta %16, koyuda %42); sert gölge kullanılmaz.

Saydamlık kapalıysa (Windows ayarı, pil tasarrufu ya da yüksek karşıtlık modu) cam yerine aynı tonda düz renk gösterilir. Program bu durumda da düzgün görünmelidir.

## Akım ışığı

Akım ışığı teldeki gerçek akımı gösterir; süs değildir.

- **Ne zaman:** yalnız bir eleman seçilince. Hiçbir şey seçili değilse ışık yanmaz.
- **Nerede:** seçili elemanın kendi kolunda, düğümden düğüme. Diğer teller hafifçe soluklaşır (opaklık %55), seçili elemanın çizgisi mavi olur.
- **Yön:** akımın gerçek yönünde. Birden çok kaynak varsa uydurma tek bir yol çizilmez; her telin akımı çözümden gelir.
- **Hız:** akımın büyüklüğüyle artar ama sakindir. Bir çizgi parçasının 48 px yol alması, en büyük akımda yaklaşık 1,7 sn, küçük akımlarda 3 sn sürer (hız oranı akım oranının karekökü). Bütün teller aynı düzende akar; her tel kendi rastgele desenini çizmez.
- **Görünüş:** 3 px'lik parlak çizgi ve altında 10 px'lik soluk hale; 14 px çizgi, 34 px boşluk.
- **Eleman kartı:** ışıkla birlikte açılır. İçinde ad, değer, akım, gerilim, güç ve o düğümdeki akım dengesi (KCL) yazar.
- **AC devreler:** sonraki adım. Işık yavaşlatılmış gösterilir ve faz farkı görünür.
- **Hareket azaltma:** Windows'ta animasyonlar kapalıysa ışık akmaz, sabit parlak çizgi olarak görünür.

## Bileşenler

**Başlık çubuğu.** 48 px yüksek, zeminin üstünde. Solda program adı ve dosya adı (soluk), sağda Dosya, Örnekler, Yeni soru, ince bir ayraç, Yardım ve tema düğmesi. Düğmeler kenarsızdır. Dosya menüsünde: Aç, Son açılanlar, Kaydet, Yazdır / PDF, Netlist oluştur, Temizle.

**Sol şerit.** 5 kategori: Pasif, Kaynak, Bağımlı, Anahtar, Ölçüm. Her öğede 22 px simge ve altında 12 px ad. Seçili öğenin hafif bir dolgusu ve solunda 3×16 px mavi çizgisi vardır. Seçili kategoriye yeniden tıklamak listeyi kapatır.

**Açılan eleman listesi.** 220 px genişliğinde, tuvalin sol üstünde yüzer. Başında kategori adı (12 px, soluk), altında 40 px yüksekliğinde satırlar. Bir eleman seçilince liste kapanır ve eleman yerleştirilmeye başlar. Tuvale tıklamak, Esc ya da aynı kategoriye yeniden basmak da listeyi kapatır. Liste devrenin bir kısmını kısa süre örter; devre kaydırılmaz.

**Araç çubuğu.** Tuvalin alt ortasında: Tel çiz, ayraç, Geri al, Yinele, ayraç, uzaklaştır, yakınlaştırma oranı, yakınlaştır, sığdır. Tel çizme açıkken düğme hafif dolgulu olur. (Taslaktaki Seç, Döndür, Sil düğmeleri şimdilik yok; bunlar klavye ve sağ tıkla yapılıyor.)

**Durum satırı.** Tuvalin altında, doğrudan zeminin üstünde, soluk renkte: "Çözüldü — 4 düğüm, 7 çözüm adımı".

**Okuma paneli.** Tek bir kâğıt kart. Üstte yöntem kutusu ile Çöz düğmesi yan yana; altında analiz türü ("DC analiz") ve çözücü durumu, gerekiyorsa terminal, frekans ve Etkin/Tepe seçimleri, en altta Alıştırma modu. İnce bir çizginin altında çözüm başlar: başarıda yalnız küçük yeşil bir "Çözüm başarılı" satırı (uyarı varsa sarı şerit), Anlatım / Sonuçlar seçimi, adım adım anlatım ve en sonda "Yapay zekâya sor". Denklemler kod bloğu içinde (paper-soft zemin, 8 px köşe, mono yazı). Grafikler kart içinde kart olmasın diye yalnız ince kenarlı kutularda durur.

**Adım geçişi.** Kâğıdın altında "‹ Önceki · Adım 2 / 8 · Düğüm Denklemleri · Sonraki ›". Anlatımın her bölümü bir adımdır. Önceki / Sonraki çözümü sayfalara bölmez, ilgili bölümün başına kaydırır; etiket kaydırdıkça o an okunan bölümü gösterir. Sonuçlar görünümünde ve tek bölümlük anlatımda gizlenir. Alttaki durum satırındaki adım sayısı aynı bölüm sayısıdır.

**Düğmeler.** Asıl düğme (Çöz) mavi dolgulu, beyaz yazılı, yarı kalın. İkincil düğmeler ince kenarlı, yarı saydam beyaz. Hepsi 6 px köşeli; Notion'un hap biçimli düğmeleri kullanılmaz.

## Erişilebilirlik

- Bütün kontroller klavyeyle ulaşılabilir; odak çerçevesi her zaman görünür (`Brush.Border.Focus`).
- Tıklanan hedefler en az 32 px yüksekliğindedir.
- Bilgi yalnız renkle verilmez: seçili eleman hem mavi olur hem de kartı açılır.
- Yüksek karşıtlık modunda Windows'un kendi renkleri kullanılır.

## WPF'de uygulama notları

- **Mica:** .NET 10'daki Fluent teması (`ThemeMode`) Windows 11'de pencereye Mica verebilir. Uygulamanın ilk adımında bizim 41 kendi stilimizle birlikte çalışıp çalışmadığı denenecek. Çalışmazsa zemin düz #F3F3F3 / #202020 olur; görünüş bozulmaz.
- **Cam:** WPF pencere içinde arka plan bulanıklaştırmayı kendisi yapmaz. Tuvalin bulanık kopyası `VisualBrush` ve `BlurEffect` ile çizilir (`tasarim-denemesi` dalındaki `Controls/GlassBackdrop.cs` başlangıç noktası). Bu yalnız tuvalin üstündeki camlar için gerekir, çünkü arkalarında yalnız tuval vardır.
- **Gölge:** WPF'de gölge tek katmanlıdır (`DropShadowEffect`). Üst kenardaki parlak çizgi, 1 px'lik ayrı bir kenarla yapılır.
- **Akım hesabı:** her telin akımı `Services/CurrentFlow.cs` içindeki düğüm akım dengesiyle bulunur (`tasarim-denemesi` dalında, testleriyle birlikte).
- **Performans:** bulanıklık pahalıdır. Cam yalnız görünürken ve gerektiğinde yeniden çizilir; devre sürüklenirken bulanıklık geçici olarak düz renge düşebilir.

## Yapılmayacaklar

- Okuma panelini, sol şeridi ya da başlık çubuğunu cam yapmak.
- İki camı yan yana ya da üst üste koymak.
- Maviyi süs için kullanmak ya da ikinci bir vurgu rengi eklemek.
- Akım ışığını her telde sürekli yakmak ya da akımdan bağımsız bir desenle oynatmak.
- Sert, koyu gölgeler.
- Hap biçimli düğmeler, renkli süs çıkartmaları, büyük reklam başlıkları (bunlar web sitesine aittir, programa değil).

## Kaynaklar

- Microsoft, "Mica material" ve "Acrylic material" (learn.microsoft.com, Windows uygulama tasarımı). Katman düzeni ve cam kullanım yerleri buradan.
- Apple, Liquid Glass yaklaşımı: camın kontrol katmanına ait olması. Apple'ın sayfası okunamadı, genel bilgiye dayanır.
- Notion tasarım dili üzerine bir inceleme (VoltAgent/awesome-design-md, MIT). Oradan alınanlar: sıcak gri yazı tonları (#31302E, #615D59, #F6F5F4), tek vurgu rengi fikri, kalın/normal yazı karşıtlığı. Metni kopyalanmadı.
- Onaylanan taslak: "Devre Analizi Taslakları", D panosu.
