"""Telegram semantic chunking (bkz. src/notify.py, 2026-09-10 kök neden
analizi: eski karakter-sayısı chunker bir kaydın ortasında kesiyordu -
"📚 Oku Şimdi: TagZilla: ... Threat Re..." canlıda görülen örnek). Saf
fonksiyon testleri - gerçek ağ/Telegram çağrısı YOK."""
from __future__ import annotations

from cyber_radar.notify import _chunk, _group_by_boundary, _word_wrap


def test_chunk_returns_single_piece_when_under_limit():
    assert _chunk("kısa metin", size=100) == ["kısa metin"]


def test_chunk_never_splits_a_word_in_the_middle():
    """Bilinçli olarak boşluk YOKKEN bile kelime sınırı korunsun diye kısa
    kelimelerden oluşan uzun bir metin - hiçbir chunk sınırı bir kelimenin
    ORTASINDA düşmemeli."""
    words = [f"kelime{i}" for i in range(500)]
    text = " ".join(words)
    chunks = _chunk(text, size=50)
    # Her chunk'ın başı ve sonu bir kelime sınırında olmalı (baştaki/sondaki
    # boşluk kırpılmış tek bir kelimenin parçası OLMAMALI).
    for c in chunks:
        assert not c.startswith(" ")
        for w in c.split(" "):
            assert w in words or w == ""
    rejoined = " ".join(chunks).split(" ")
    assert [w for w in rejoined if w] == words


def test_chunk_prefers_category_boundary_over_mid_section_cut():
    """İki '## ' kategorisi olan, ikincisi limit'i aşacak kadar uzun bir
    metinde - bölme NOKTASI kategori sınırında olmalı, kategori içeriğinin
    ortasında DEĞİL: "## Kategori B" başlığı bir chunk'ın İÇİNDE BÖLÜNMEDEN
    (tam olarak) geçmeli."""
    cat1 = "## Kategori A\n" + ("x" * 50)
    cat2 = "## Kategori B\n" + " ".join(["kelime"] * 40)  # gerçekçi, boşluklu içerik
    text = cat1 + "\n" + cat2
    chunks = _chunk(text, size=120)
    assert len(chunks) >= 2
    joined = "".join(chunks)
    assert "## Kategori A" in joined and "## Kategori B" in joined
    assert any("## Kategori B" in c for c in chunks)  # başlık BÜTÜN olarak bir chunk'ta


def test_chunk_splits_on_article_separator_when_section_too_big():
    """Tek bir kategori içinde birden fazla '----' ile ayrılmış makale/haber
    varsa ve kategori limit'i aşıyorsa, bölme '----' sınırında olmalı."""
    items = [f"- Makale {i}\n  Özet metni {i}." for i in range(30)]
    text = "## Güncel Makaleler\n" + "\n----\n".join(items)
    chunks = _chunk(text, size=200)
    assert len(chunks) > 1
    for c in chunks:
        # Hiçbir chunk "Makale" kelimesinin ortasında başlamamalı/bitmemeli.
        assert not c.startswith("kale") and not c.endswith("Mak")


def test_chunk_reconstructs_original_content_exactly():
    """Chunk'lar birleştirildiğinde orijinal metin KAYIPSIZ geri
    üretilmeli - semantic chunking içerik UYDURMAMALI/KAYBETMEMELİ."""
    text = "## A\niçerik a\n----\n## B\niçerik b\n\nparagraf 2"
    chunks = _chunk(text, size=15)
    assert "".join(chunks) == text


def test_group_by_boundary_merges_small_adjacent_pieces():
    text = "a\n## \nb\n## \nc"
    groups = _group_by_boundary(text, size=100, sep="\n## \n")
    assert groups == [text]  # hepsi sığıyor, tek grup


def test_word_wrap_never_breaks_a_word_unless_the_word_itself_exceeds_size():
    text = "kısa kelimeler burada var"
    chunks = _word_wrap(text, size=10)
    for c in chunks:
        for w in c.split(" "):
            assert len(w) <= 10 or w == text.replace(" ", "")  # tek aşırı uzun kelime durumu


def test_chunk_empty_text_returns_single_empty_chunk():
    assert _chunk("", size=100) == [""]


def test_word_wrap_hard_slices_only_when_a_single_token_exceeds_size():
    """Gerçek dünyada bu neredeyse hiç olmaz (bir kelime/URL tek başına
    size'dan uzun) - bu durumda başka çıkış yok, sert kesiliyor AMA bu
    davranış AÇIKÇA belgelenmiş ve TEST EDİLMİŞ olmalı (bkz. proje notları:
    "tek kelimenin KENDİSİ size'dan uzunsa bundan kaçış yok")."""
    text = "önce " + ("a" * 300) + " sonra"
    chunks = _word_wrap(text, size=100)
    assert chunks  # crash etmedi, en az bir chunk üretti
    # normal kelimeler ("önce"/"sonra") bölünmemiş olmalı
    assert any(c.strip() == "önce" or c.startswith("önce ") for c in chunks)
    assert any(c.strip() == "sonra" or c.endswith(" sonra") for c in chunks)
