# Primärquellen

Die Erweiterung und ihre Konfigurationsdateien beziehen sich auf diese
technischen Schnittstellen. Die Links sind keine Empfehlung, fremde
Sicherheitsrichtlinien oder Anbieterbedingungen zu umgehen.

## MediaMTX

- Konfigurationsreferenz, Version 1.21.3:
  https://mediamtx.org/docs/references/configuration-file
- Externe HTTP-Authentifizierung und RTMP-Zugangsdaten:
  https://mediamtx.org/docs/features/authentication
- OBS als RTMP-Publisher:
  https://mediamtx.org/docs/publish/obs-studio
- HLS und Browser-Wiedergabe:
  https://mediamtx.org/docs/read/web-browsers
- API-Schema der fixierten Version:
  https://raw.githubusercontent.com/bluenviron/mediamtx/v1.21.3/api/openapi.yaml

## Player

- hls.js, Release 1.7.4:
  https://github.com/video-dev/hls.js/releases/tag/v1.7.4
- Beim Installieren verwendete versionierte Datei:
  https://cdn.jsdelivr.net/npm/hls.js@1.7.4/dist/hls.min.js
- Lizenz:
  https://cdn.jsdelivr.net/npm/hls.js@1.7.4/LICENSE

## OBS

- Offizielle Webseite:
  https://obsproject.com/
- Offizielle Windows-Installation:
  https://obsproject.com/kb/windows-installation

## Cloudflare

- Quick Tunnels und ihre Grenzen:
  https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
- Einstellungen für Upload-Grössen:
  https://developers.cloudflare.com/network/maximum-upload-size/
- Anbieterbedingungen, insbesondere CDN/Video:
  https://www.cloudflare.com/service-specific-terms-application-services/

## Weitere technische Grundlagen

- Go-HTTP-Client: Basic-Authentifizierung aus URL-Zugangsdaten für den internen
  MediaMTX-Callback:
  https://go.dev/src/net/http/client.go
- FastAPI-Hintergrundaufgaben:
  https://fastapi.tiangolo.com/tutorial/background-tasks/
- SQLite-Transaktionen:
  https://www.sqlite.org/lang_transaction.html

Der Chunk-Uploader ist projektspezifischer Code und keine Implementierung des
tus-Protokolls. Er ist nicht als S3-Multipart-Upload auszugeben.
