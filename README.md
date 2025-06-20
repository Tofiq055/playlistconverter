# Spotify to YouTube Playlist Converter

A CLI tool to transfer your Spotify playlists to YouTube (Music) playlists—no web app, no leaks, all local.

## Features

- Convert one or multiple Spotify playlists to YouTube at once
- Fuzzy search for better song matches
- Skips duplicate tracks and avoids duplicate playlists
- Progress bars (tqdm)
- Automatic retry on quota errors
- Caches YouTube video matches for speed and quota saving
- Exports any failed tracks to `failed_tracks.txt`
- Uses `.env` file for secrets—your API keys stay private

## Requirements

- Python 3.8+
- Spotipy
- Google API Client
- FuzzyWuzzy
- tqdm
- python-dotenv

Install requirements:
```bash
pip install spotipy google-auth google-auth-oauthlib google-api-python-client fuzzywuzzy python-Levenshtein tqdm python-dotenv

