# Solana Meme Paper Trader

Starter project Python untuk memantau event launch Solana, memeriksa bukti risiko, dan mencatat simulasi trade lokal. Mode otomatis yang tersedia hanya **paper trading**. Tidak ada wallet, private key, fungsi signing, pembuatan instruksi swap, atau pengiriman transaksi.

## Yang tersedia

- Adapter GraphQL Bitquery read-only untuk event launch Pump.fun, Raydium Launchpad, Meteora DBC, Heaven, Moonit, serta penandaan event Bags/Jupiter Studio bila akun pemicunya terdekode.
- Kuotasi USD dari trade Solana terakhir yang tersedia di Bitquery; harga ini adalah data trade, bukan quote eksekusi atau jaminan likuiditas.
- Adapter GET RugCheck dengan normalisasi field yang harus dipetakan secara eksplisit. Field yang tidak diketahui tetap `null` dan akan memblokir paper entry.
- Gerbang entry konservatif: report harus cocok dengan mint, masih segar, melewati batas likuiditas dan konsentrasi holder, authority harus diketahui nonaktif, dan tidak boleh ada risk flags.
- Ledger SQLite lokal, posisi dan P/L terealisasi, serta simulasi fee, slippage, batas ukuran, quote stale, dan latency yang dimodelkan.
- Proposal trade berbentuk JSON hanya setelah fitur proposal diaktifkan secara eksplisit. Proposal bukan order dan bukan transaksi Solana; pengguna harus memverifikasi ulang, menyusun, dan menandatangani sendiri di wallet/DEX tepercaya.

## Batas keselamatan yang disengaja

`app.mode` harus `paper`; nilai lain ditolak. `live.execution_enabled` harus tetap `false` dan konfigurasi ditolak jika diubah menjadi `true`. Tidak ada kode yang dapat mengirim order nyata. Proposal live juga mati secara default, bukan instruksi siap-sign, dan perlu dua langkah opt-in: mengubah `live.proposals_enabled` menjadi `true` lalu memanggil CLI dengan `--confirm-proposal-only`.

Ledger ini hanya menyimpan simulasi baru pada `state/ledger.sqlite3`. Proyek tidak membaca, mengubah, atau mengimpor ledger/proyek lain. Database lama tidak di-reset bila saldo awal pada konfigurasi berubah.

## Mulai

Gunakan Python 3.11 atau lebih baru:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
```

Atur `BITQUERY_API_KEY` sebagai environment variable proses melalui shell atau pengelola environment Anda sebelum memakai kueri Bitquery. Jangan masukkan API key ke `config.toml`, `.env` yang ter-commit, argumen CLI, log, atau issue publik.

```bash
smp config-check --config config.toml
```

CLI tidak memuat file `.env` secara otomatis. File `.env.example` hanya pengingat variabel yang dibutuhkan.

### Temukan launch dan kuotasi

```bash
smp discover --config config.toml
smp quote --config config.toml --mint <TOKEN_MINT>
```

Query launch berasal dari contoh resmi Bitquery. Mint hanya ditandai siap dipakai bila Bitquery mengembalikan tepat satu `Token.Mint`; jika field tidak jelas/ambigu, proyek tidak menebak mint. Periksa hasil di sumber tepercaya sebelum melakukan simulasi.

### Siapkan bukti risiko lalu paper trade

```bash
smp risk-fetch --config config.toml --mint <TOKEN_MINT> --out state/risk-raw/<MINT>.json
```

Laporan raw disimpan apa adanya. Skema laporan provider dapat berubah dan dokumentasi endpoint tidak menjanjikan semua field risiko selalu tersedia. Setelah memeriksa laporan terbaru, isi `[risk.field_map]` di `config.toml` dengan path JSON yang benar-benar Anda verifikasi, lalu jalankan ulang dengan `--normalized-out`. Path yang tidak dipetakan menghasilkan nilai unknown dan entry tetap ditolak. Alternatifnya, buat JSON sesuai [`risk-evidence.example.json`](examples/risk-evidence.example.json) dari bukti terbaru dan tepercaya.

```bash
smp risk-fetch --config config.toml --mint <TOKEN_MINT> \
  --out state/risk-raw/<MINT>.json \
  --normalized-out state/risk/<MINT>.json
smp paper buy --config config.toml --mint <TOKEN_MINT> --usd 10 \
  --risk-file state/risk/<MINT>.json
smp paper status --config config.toml
smp paper status --config config.toml --mark
smp paper sell --config config.toml --mint <TOKEN_MINT> --quantity 1000
```

`--usd` adalah total anggaran cash termasuk fee simulasi. Sell menggunakan jumlah token. Fill memakai quote trade terakhir yang lolos batas umur; trade tidak dikirim ke blockchain. `paper status` menampilkan cash, posisi, fee dan realized P/L. Opsi `--mark` membaca quote Bitquery segar untuk menghitung unrealized P/L sementara, tanpa menyimpan quote mark ke ledger; jika satu posisi tidak dapat ditandai dengan aman, total unrealized P/L tetap `null`.

### Proposal non-eksekutabel

Setelah membaca batasannya, proposal dapat diaktifkan di `[live]`:

```toml
[live]
proposals_enabled = true
execution_enabled = false
```

Lalu:

```bash
smp proposal create --config config.toml --mint <TOKEN_MINT> \
  --side buy --amount 10 --confirm-proposal-only
```

Hasilnya hanya file JSON dengan mint, sisi, jumlah, harga referensi, batas slippage, fee estimasi, sumber/waktu quote, dan waktu kedaluwarsa. File itu **tidak** berisi transaksi, route DEX, akun, wallet, tanda tangan, atau endpoint pengiriman. Jangan anggap itu order yang siap dieksekusi.

## Konfigurasi penting

`config.example.toml` menetapkan saldo simulasi awal $1,000, fee 100 bps, slippage 100 bps, batas quote 15 detik, trade maksimal $25, posisi maksimal $100, dan risk gate minimal likuiditas $5,000 serta konsentrasi holder maksimum 20%. Ubah hanya setelah memahami asumsi. Fee, slippage, dan latency adalah parameter simulasi—bukan prediksi fill nyata.

RugCheck pada layanan gratis dapat membatasi laju dan report yang hanya tersedia dari cache; fitur refresh berbayar tidak dipanggil. Jangan mengandalkan hasil scanner sebagai jaminan aman.

## Uji

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Uji berjalan offline dengan fixture: tidak memakai API key, tidak membuat trade nyata, dan tidak menyentuh wallet.

## API dan sumber dokumentasi

- [Bitquery Solana Instructions API](https://docs.bitquery.io/docs/blockchain/Solana/solana-instructions/) — contoh event token creation dan launchpad multi-protokol.
- [Bitquery Solana DEX Trades](https://docs.bitquery.io/docs/blockchain/Solana/solana-dextrades/) — contoh `DEXTradeByTokens`, `PriceInUSD`, dan waktu blok.
- [RugCheck API overview](https://rugcheck.xyz/api) dan [OpenAPI/Swagger](https://api.rugcheck.xyz/swagger/index.html) — endpoint GET laporan token dan batas layanan.

## Referensi repositori dan lisensi

Proyek ini ditulis baru; **tidak ada source code dari repositori berikut yang disalin atau dibundel**. Rujukan hanya untuk membandingkan cakupan/ide integrasi. Metadata lisensi diperiksa pada GitHub saat proyek disiapkan:

- [GMGNAI/gmgn-skills](https://github.com/GMGNAI/gmgn-skills) — lisensi terdeteksi: MIT.
- [kukapay/rug-check-mcp](https://github.com/kukapay/rug-check-mcp) — MIT.
- [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) — Apache-2.0.
- [sendaifun/solana-agent-kit](https://github.com/sendaifun/solana-agent-kit) — Apache-2.0.
- [AtlasOnchain/Atlas](https://github.com/AtlasOnchain/Atlas) — tidak ditemukan lisensi/berkas `LICENSE`; karena itu kodenya tidak digunakan.

Kode baru proyek ini dilisensikan MIT; lihat [`LICENSE`](LICENSE).

## Bukan sistem produksi

Ini adalah starter untuk eksperimen paper-trade, bukan rekomendasi investasi atau sistem yang membuktikan sebuah token aman. Ia belum mengukur depth/slippage pool yang dapat dieksekusi, tidak mengaudit kontrak/program penuh, tidak memastikan kualitas setiap report risiko, dan tidak menjalankan strategi trading otomatis. Data launch/quote API dapat tertunda, terlewat, atau tidak tersedia; layanan dapat membatasi akses. Selalu verifikasi token mint dan report secara independen.
