import json
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from langdetect import detect
from moviepy.editor import AudioFileClip
from mutagen.id3 import ID3, ID3NoHeaderError, TPE1, TALB, TPE2, TDRC, APIC, USLT
from pytube import YouTube
from pytube.exceptions import VideoUnavailable, RegexMatchError, LiveStreamError
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from youtube_search import YoutubeSearch

from langMap import languageMapping

# Configure logging
logging.basicConfig(
    filename='spotifyDownloader.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Starts a performance counter
start = time.perf_counter()

# Function to move the downloaded playlist directory to another directory
# I personally use this for moving the downloaded playlist folder inside Apple Music folder
# That way the songs are directly moved into Music app.
def movePlaylistFolder(playlistDir, destinationDir):
    try:
        # Try to move the folder to destination
        shutil.move(playlistDir, destinationDir)
        print("Playlist folder moved successfully.")
    except Exception as e:
        print(f"Error moving playlist folder: {e}")

# This is used when we add Lyrics to the song's metadata
def isoLangConvert(lang):
    # Fetches the 3 alphabet code of the language
    convertedLanguage = languageMapping.get(lang)
    if not convertedLanguage:
        raise ValueError(f"No language mapping found for {lang}")
    return convertedLanguage

# Gets lyrics from lyrics.ovh API
def getLyrics(artist, trackTitle):
    # This is done because of something I noticed
    # When I searched for the song's lyrics, usually the first name of the artist of the song was shown
    # This sets the artist to the first artist's name
    newArtist = artist.split(",")
    artist = newArtist[0]
    # Set a URL
    url = f"https://api.lyrics.ovh/v1/{artist}/{trackTitle}"
    try:
        response = requests.get(url)  # Try to get the json from URL
        response.raise_for_status()  # Raise exception for HTTP errors
        jsonData = response.json()  # Load the response data as json
        lyrics = jsonData['lyrics']  # Get the lyrics as string
        return lyrics
    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching lyrics: {e}")
        raise

# Updates the MetaData of a Song
def updateMetaData(filePath, trackTitle, artist, albumName, albumArtists, releaseDate, imageUrl):
    try:
        audio = ID3(filePath)
    except ID3NoHeaderError:
        audio = ID3()

    # Remove existing USLT frames
    usltKeys = [key for key in audio.keys() if key.startswith('USLT')]
    for key in usltKeys:
        audio.delall(key)

    # Add basic metadata
    audio.add(TPE1(encoding=3, text=artist))  # Artist Name
    audio.add(TALB(encoding=3, text=albumName))  # Album Name
    audio.add(TPE2(encoding=3, text=albumArtists))  # Album Artists
    audio.add(TDRC(encoding=3, text=releaseDate))  # Release Date

    # Download and embed album art
    try:
        imageResponse = requests.get(imageUrl)
        imageResponse.raise_for_status()
        imageData = imageResponse.content
        mimeType = "image/jpeg"
        image = APIC(
            encoding=3,
            mime=mimeType,
            type=3,
            desc=os.path.basename(imageUrl),
            data=imageData,
        )
        audio.delall("APIC")  # Deletes the APIC metadata which the mp3 might have 
        audio.add(image)  # Adds in the image / artwork to the metadata
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to download or embed album art: {e}")
        raise

    # Add lyrics
    try:
        lyrics = getLyrics(artist, trackTitle)  # Get lyrics
        lyricsLang = detect(lyrics)  # detect the language of the lyrics. Outputs the language in 2 alphabet code
        newLyricsLang = isoLangConvert(lyricsLang)  # Gets the 3 alphabet language code
        # Adds in the Unsynced Lyrics to MP#
        audio[u"USLT::" + newLyricsLang] = USLT(encoding=3, lang=newLyricsLang, desc=u'desc', text=lyrics)
    except Exception as e:
        logging.error(f"Error adding lyrics: {e}")
        raise

    # Save metadata changes
    try:
        audio.save(filePath)
    except Exception as e:
        logging.error(f"Error saving metadata: {e}")
        raise

# Downloads the Audio as mp3
def downloadAudio(url, outputPath, title):
    try:
        ytAudObj = YouTube(url)
        audioStream = ytAudObj.streams.filter(only_audio=True).first() # Gets the first stream which is audio only.
        tempFile = audioStream.download(outputPath) # Saves the audio in a temp file
        audioClip = AudioFileClip(tempFile)
        audioClip.write_audiofile(os.path.join(outputPath, f"{title}.mp3"), verbose=False, logger=None) # convers the temp file to an mp3
        audioClip.close()
        os.remove(tempFile) # Removes the Temp file
        return True
    except VideoUnavailable:
        logging.error(f"Video {url} is unavailable.")
        return False
    except RegexMatchError:
        logging.error("Error: Invalid YouTube URL")
        return False
    except LiveStreamError:
        logging.error("Error: Video is a live stream")
        return False
    except Exception as e:
        logging.error(f"An error occurred while downloading audio: {e}")
        raise

# Retries an operation
def retry(operation, attempts, delay):
    for attempt in range(attempts):
        try:
            result = operation()
            if result:
                return result
        except Exception as e:
            logging.warning(f"Attempt {attempt + 1} failed: {e}")
        print(f"Retrying in {delay} seconds...")
        time.sleep(delay)
    logging.error(f"All {attempts} attempts failed.")
    return None

# Function to retry audio download if it fails
# You can change the number of attempts
# You can also change the delay (in seconds)
def downloadAudioWithRetry(url, outputPath, title, attempts=3, delay=5):
    def operation():
        return downloadAudio(url, outputPath, title)
    return retry(operation, attempts, delay)

# Goes over a playlist and perform the necessary steps
def processPlaylist(playlistLink, baseOutputPath):
    # Check if the playlist URL is valid
    match = re.match(r"https://open.spotify.com/playlist/(.*)\?", playlistLink)
    if match:
        playlistUri = match.groups()[0]
    else:
        raise ValueError("Expected format: https://open.spotify.com/playlist/...")

    playlist = session.playlist(playlistUri) # Initialise a playlist session
    playlistName = playlist['name']  # Gets the playlist name
    # Sanitizes the playlist name and removes any characters which might create an issue    
    sanitizedPlaylistName = "".join(char for char in playlistName if char.isalnum() or char in (' ', '_', '-')).rstrip()
    # Checks if the playlist name is available if not then sets to to "playlist"
    if not sanitizedPlaylistName:
        sanitizedPlaylistName = "playlist"
    # Make a New directory in the download location with playlist name
    playlistDir = os.path.join(baseOutputPath, sanitizedPlaylistName)
    os.makedirs(playlistDir, exist_ok=True)

    print(f"Processing playlist: {playlistName}")

    # Gets the data of the playlist
    playlistData = playlist["tracks"]["items"]

    # Use ThreadPoolExecuter for concurrent downloading
    # Cut down the time to 30%
    # Tried with the Top 50 - Global
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []

        for track in playlistData:
            futures.append(executor.submit(downloadAndProcessTrack, track, playlistDir))

        for future in as_completed(futures):
            try:
                future.result()
            except Exception as e:
                logging.error(f"Error processing track: {e}")

def downloadAndProcessTrack(track, playlistDir):
    # Extracting all the necessary info about a track
    name = track["track"]["name"]
    artists = ", ".join([artist["name"] for artist in track["track"]["artists"]])
    image = track["track"]["album"]["images"][0]["url"]
    albumName = track["track"]["album"]["name"]
    albumArtists = ", ".join([artist["name"] for artist in track["track"]["album"]["artists"]])
    releaseDate = track["track"]["album"]["release_date"]
    # Sets Track title to contain (Official Audio) because some songs on YouTube have this seperately
    trackTitle = f"{name} (Official Audio) - {artists}"

    # Gets the first result and saves it as JSON
    sResult = YoutubeSearch(trackTitle, max_results=1).to_json()
    resultData = json.loads(sResult)
    if resultData['videos']:
        # setting up the YouTube URL for downloading the audio
        urlSuffix = resultData['videos'][0]['url_suffix']
        youtubeURL = f"https://www.youtube.com{urlSuffix}"

        # if the Download succeds then tries to update MetaData
        if downloadAudioWithRetry(youtubeURL, playlistDir, name):
            mp3FilePath = os.path.join(playlistDir, f"{name}.mp3")
            try:
                updateMetaData(mp3FilePath, name, artists, albumName, albumArtists, releaseDate, image)
                print(f"Downloaded and updated metadata for: {name}")
            except Exception as e:
                logging.error(f"Failed to update metadata for {name}: {e}")
        else:
            logging.error(f"Failed to download audio for: {name}")
    else:
        logging.error(f"No YouTube results for: {trackTitle}")

# Main execution
load_dotenv()

# Get the necessary info from .env file
clientId = os.getenv("CLIENT_ID")
clientSecret = os.getenv("CLIENT_SECRET")

clientCredentialsManager = SpotifyClientCredentials(client_id=clientId, client_secret=clientSecret)
session = spotipy.Spotify(client_credentials_manager=clientCredentialsManager)

# List of playlist to be downloaded
"""
Format should be: 
playlistLinks = [
    "Playlist 1",
    "Playlist 2",
         .
         .
         .
    "Playlist n"
]
"""
playlistLinks = [
    "https://open.spotify.com/playlist/37i9dQZEVXbMDoHDwVN2tF?si=045ae33b3abd4a50"
]

# Output path where the playlist should be downloaded
outputPath = "/path/to/save/location"

# Open the Log file
with open('spotifyDownloader.log', 'w'):
    pass

# Loop over each playlist
for playlistLink in playlistLinks:
    processPlaylist(playlistLink, outputPath)

logging.info("Process complete.")

# Another Performance counter
finish = time.perf_counter()

# Display the total time taken in running the code
print(f"Finished in {round(finish - start, 2)} second(s)")
