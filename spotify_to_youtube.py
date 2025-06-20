import os
import json
import time
from pathlib import Path

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from fuzzywuzzy import fuzz
from tqdm import tqdm

# Load environment variables
load_dotenv()
SPOTIFY_CLIENT_ID = os.environ.get('SPOTIPY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.environ.get('SPOTIPY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.environ.get('SPOTIPY_REDIRECT_URI')
YOUTUBE_CLIENT_SECRET_FILE = 'client_secret.json'
SPOTIFY_SCOPE = 'playlist-read-private'
YOUTUBE_SCOPE = ['https://www.googleapis.com/auth/youtube.force-ssl']
CACHE_FILE = 'video_cache.json'
FAILED_TRACKS_FILE = 'failed_tracks.txt'

def load_cache():
    if Path(CACHE_FILE).exists():
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2)

def log_failed_track(track, playlist_name):
    with open(FAILED_TRACKS_FILE, 'a', encoding='utf-8') as f:
        f.write(f'[{playlist_name}] {track}\n')

def authenticate_spotify():
    return spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
        redirect_uri=SPOTIFY_REDIRECT_URI,
        scope=SPOTIFY_SCOPE
    ))

def authenticate_youtube():
    flow = InstalledAppFlow.from_client_secrets_file(
        YOUTUBE_CLIENT_SECRET_FILE, scopes=YOUTUBE_SCOPE)
    credentials = flow.run_local_server(port=0)
    return build('youtube', 'v3', credentials=credentials)

def get_spotify_tracks(sp, playlist_id):
    playlist_info = sp.playlist(playlist_id)
    playlist_name = playlist_info['name']
    tracks = []
    results = sp.playlist_tracks(playlist_id)
    while results:
        for item in results['items']:
            track = item['track']
            if track:
                name = track['name']
                artist = track['artists'][0]['name']
                tracks.append(f"{name} {artist}")
        if results['next']:
            results = sp.next(results)
        else:
            results = None
    return playlist_name, tracks

def get_youtube_playlist_by_name(youtube, name):
    request = youtube.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50
    )
    while request is not None:
        response = request.execute()
        for item in response['items']:
            if item['snippet']['title'] == name:
                return item['id']
        request = youtube.playlists().list_next(request, response)
    return None

def create_youtube_playlist(youtube, title):
    request = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {"title": title, "description": "Imported from Spotify"},
            "status": {"privacyStatus": "private"}
        }
    )
    response = request.execute()
    return response['id']

def get_video_ids_in_playlist(youtube, playlist_id):
    video_ids = set()
    nextPageToken = None
    while True:
        request = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=nextPageToken
        )
        response = request.execute()
        for item in response['items']:
            video_ids.add(item['snippet']['resourceId']['videoId'])
        nextPageToken = response.get('nextPageToken')
        if not nextPageToken:
            break
    return video_ids

def retry(func, *args, **kwargs):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except HttpError as e:
            if e.resp.status in [403, 409, 429, 500, 503]:
                sleep_time = 2 ** attempt
                print(f"Quota/temporary error (attempt {attempt+1}), retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                raise

def fuzzy_search_youtube(youtube, query, original_title, cache):
    if original_title in cache:
        return cache[original_title]

    response = retry(
        youtube.search().list,
        q=query, part='snippet', type='video', maxResults=5
    ).execute()

    best_score = 0
    best_video_id = None
    for item in response['items']:
        video_title = item['snippet']['title']
        score = fuzz.token_set_ratio(video_title.lower(), original_title.lower())
        if score > best_score:
            best_score = score
            best_video_id = item['id']['videoId']

    if best_video_id:
        cache[original_title] = best_video_id
    return best_video_id

def add_to_youtube_playlist(youtube, playlist_id, video_id):
    retry(
        youtube.playlistItems().insert,
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": video_id
                }
            }
        }
    ).execute()

def convert_playlist(sp, youtube, spotify_playlist_id, cache):
    playlist_name, tracks = get_spotify_tracks(sp, spotify_playlist_id)
    print(f"\n🎧 Converting: {playlist_name}")

    yt_playlist_id = get_youtube_playlist_by_name(youtube, playlist_name)
    if yt_playlist_id:
        print(f"Found existing playlist: {playlist_name}")
    else:
        yt_playlist_id = create_youtube_playlist(youtube, playlist_name)
        print(f"Created new playlist: {playlist_name}")

    existing_video_ids = get_video_ids_in_playlist(youtube, yt_playlist_id)

    for track in tqdm(tracks, desc=f"Adding to {playlist_name}"):
        video_id = fuzzy_search_youtube(youtube, track, track, cache)
        if not video_id:
            log_failed_track(track, playlist_name)
            print(f"✗ Not Found: {track}")
            continue
        if video_id in existing_video_ids:
            continue  # Don't add duplicates
        add_to_youtube_playlist(youtube, yt_playlist_id, video_id)
        existing_video_ids.add(video_id)

if __name__ == '__main__':
    print("==== Spotify to YouTube Music Playlist Converter ====")
    print("NOTE: Make sure your credentials, '.env', and 'client_secret.json' are set up!\n")

    sp = authenticate_spotify()
    youtube = authenticate_youtube()
    cache = load_cache()

    playlist_ids = input("Enter Spotify playlist IDs (comma-separated): ").split(',')
    playlist_ids = [p.strip() for p in playlist_ids if p.strip()]

    for pid in playlist_ids:
        try:
            convert_playlist(sp, youtube, pid, cache)
        except Exception as e:
            print(f"❌ Error converting {pid}: {e}")

    save_cache(cache)
    print("\n✅ Done! If any tracks failed, check 'failed_tracks.txt'.")
