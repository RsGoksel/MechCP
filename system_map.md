# Stealth Browser MCP System Map

<!-- 
Bu dosya projenin statik anatomisini tanımlar. LLM agent'lar projenin yapısını, amacını, tech stack'ini, giriş noktalarını ve dosya haritasını anlamak için bu dosyayı okumalıdır. 
Her büyük mimari/yapısal gelişmede bu dosyayı (system_map.md) güncelleyin.
-->

## Context Dosyaları Rehberi

| Görev Türü | Oku | Açıklama |
|------------|-----|----------|
| Proje yapısı, dosya haritası, tech stack | **system_map.md** (bu dosya) | Projenin statik anatomisi |
| Günlük değişiklikler, ne yapıldı | **Developments.md** | Kronolojik changelog (Değişiklik günlüğü) |
| Ana kurulum ve kullanım özeti | **README.md** | Kurulum, araç (tool) bölümleri ve genel bakış |

> Eski kayıtlar/dokümanlar varsa `docs/archive/` klasöründedir. Gerekmedikçe arşive bakma.

## Project Overview

Stealth Browser MCP, Claude ve diğer AI agent'larına "algılanamayan" (undetectable) tarayıcı otomasyonu yetenekleri kazandıran bir Model Context Protocol (MCP) sunucusudur. Geliştiriciler ve AI sistemleri için tasarlanmış olup, Cloudflare ve benzeri gelişmiş anti-bot korumalarını aşarak ağ trafiğini dinleme (network interception), dinamik hook yazma ve CDP (Chrome DevTools Protocol) seviyesinde UI klonlama gibi işlemleri yapmayı sağlar.

**Proje Türü:** MCP Server / AI Tooling / CLI Tool

## Related Documentation

- Location: Root dizin (`/`)
- `README.md` - [Link](./README.md) - Proje kurulumu, argüman bayrakları (`--minimal` vb.) ve desteklenen özellikler.

## Entry Points / URLs / Endpoints

Bu proje bir CLI ve MCP Sunucusu olarak çalışır. Geleneksel HTTP Endpoint'leri yerine MCP araçları (tools) sunar.

| Entry Point | Command / Araç Grubu | Açıklama |
|-------------|----------------------|----------|
| **CLI Server** | `python src/server.py` | Tüm özellikleri (full) başlatır. |
| **CLI Minimal** | `python src/server.py --minimal` | Sadece temel browser ve DOM araçlarını yükler. |
| **MCP: Browser** | `spawn_browser`, `navigate` vb. | Tarayıcı yönetimi araçları. |
| **MCP: Element** | `query_elements`, `type_text` vb. | Sayfa içi etkileşim araçları. |
| **MCP: Network** | `list_network_requests` vb. | Ağ trafiğini izleme ve dinleme araçları. |
| **MCP: Hooking** | `create_dynamic_hook` vb. | Python ile AI üzerinden dinamik request hook yazma araçları. |
| **MCP: CDP** | `execute_cdp_command` vb. | Chrome DevTools Protocol işlemleri. |

## Tech Stack

**Ana Katman (MCP Server & Browser Automation):**

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.8+ | Ana geliştirme dili |
| FastMCP | 2.11.2 | MCP (Model Context Protocol) sunucu altyapısı |
| nodriver | 0.47.0 | Algılanamayan (undetected) tarayıcı otomasyon kütüphanesi |
| pydantic | 2.11.7 | Veri validasyonu, parametre modelleme |
| py2js | Özel Fork | Tarayıcıya inject edilecek Python kodlarını JS'e çevirmek için |

**Mimari Diyagram (ASCII):**
[AI Agent (Claude)] <--(MCP/stdio)--> [FastMCP Server (server.py)] <--(CDP/WebSocket)--> [Chrome/Chromium Browser]

## Data Layer

**Bu proje kalıcı bir veritabanı (DB) kullanmaz.**

- Tarayıcı instance'ları, açık tablar ve intercept edilen ağ istekleri memory'de (RAM) dictionary objeleri üzerinde saklanır.
- Klonlanan UI elementleri (HTML, CSS, JS) local diske text/JSON/HTML dosyaları olarak geçici/kalıcı biçimde yazılabilir (`extract_element_styles_to_file` vb. araçlarla).
- Dinamik Hook kuralları ve hata ayıklama (debug) logları memory'de tutulur, istenildiğinde diske aktarılır (`export_debug_logs`).

## Authentication & Security

- **İletişim Güvenliği:** MCP standartlarına uygun olarak `stdio` (standard input/output) üzerinden yerel iletişim kurar. Ek bir API Key veya Auth token'a ihtiyaç duymaz (local trusted tool).
- **Tarayıcı Korumaları:** `--no-sandbox` gibi bayrakları platforma göre (Root/Docker durumuna göre) otomatik ayarlar (`validate_browser_environment`).
- Bu proje dışa açık (public) bir internet servisi (web API) açmaz, sadece bilgisayarı/ortamı çalıştıran kullanıcıya aittir.

## Project Structure

`/`
├── src/
│   ├── server.py                        # Ana MCP sunucu başlatıcı dosyası (Tüm araçlar burada toplanır)
│   ├── browser_manager.py               # Tarayıcı yaşam döngüsü (spawn, close, tabs)
│   ├── dom_handler.py                   # DOM etkileşimi (click, query, type)
│   ├── network_interceptor.py           # Ağ isteklerini/cevaplarını yakalama
│   ├── dynamic_hook_system.py           # Özel network kural/hook sistemi
│   ├── cdp_function_executor.py         # CDP komutları, JS inject etme
│   ├── element_cloner.py                # Standart UI Element klonlama
│   ├── file_based_element_cloner.py     # Dosya sistemine yazan element klonlama
│   ├── cdp_element_cloner.py            # Direkt CDP API ile element klonlama
│   ├── comprehensive_element_cloner.py  # Tüm varlıklarıyla klonlama (assets, css)
│   ├── progressive_element_cloner.py    # Aşamalı genişletilen element verisi çekme
│   ├── response_stage_hooks.py          # Sunucu cevabını (response body) değiştirme hook'ları
│   ├── hook_learning_system.py          # AI agent'ın dinamik hook yazmayı öğrenmesi için helper'lar
│   ├── debug_logger.py                  # Log ve debug sistem yöneticisi
│   ├── models.py                        # Ortak kullanılan Pydantic / Veri modelleri
│   ├── platform_utils.py                # İşletim sistemi (OS/Docker/Root) tespiti ve uyumluluk
│   ├── process_cleanup.py               # Asılı kalan tarayıcı process'lerini temizleme
│   └── js/                              # Tarayıcıda çalıştırılacak JavaScript kodları
│       ├── extract_styles.js            # Node'dan CSS stilleri çıkarma
│       └── ...                          # Diğer client-side extraction scriptleri
├── pyproject.toml                       # Python bağımlılıkları ve meta veri
├── README.md                            # Kurulum ve genel bilgiler
└── system_map.md                        # Bu dosya (Sistem anatomisi)

## Key Components / Modules

| Module / Component | File | Purpose |
|--------------------|------|---------|
| **Server / Entry** | `server.py` | FastMCP instance'ını oluşturur, alt modüllerden tüm araçları (tools) import edip MCP üzerinden AI'a açar. |
| **Browser Core** | `browser_manager.py` | `nodriver` kullanarak undetected browser örneklerini (instance) yaratır, tab'ları yönetir. |
| **DOM Interaction** | `dom_handler.py` | Sayfadaki elementleri seçme, tıklama, hızlı metin yapıştırma (paste_text) ve yazma işlemleri. |
| **Network & Intercept** | `network_interceptor.py` | Tüm ağ trafiğini CDP üzerinden dinleme ve loglama (headers, body vb.). |
| **Dynamic Hooks** | `dynamic_hook_system.py` | Gelen istekleri canlı olarak durdurma, modify etme veya engelleme mantığı (Python tabanlı). |
| **UI Extraction** | `*_cloner.py` dosyaları | Bir web sayfasındaki elementlerin (div, tablo vs.) birebir kopyasını tüm stil/animasyon/asset'leri ile dışa aktarma araçları. |
| **CDP & Execution** | `cdp_function_executor.py` | Sayfada Python / JS kodu çalıştırma ve CDP metotlarını doğrudan kullanma. |
| **Environment Tools**| `platform_utils.py` | Çalışma ortamı güvenliğini sağlama (Root mu? Docker mı? Windows mu? uygun argümanları oluşturma). |
