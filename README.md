# Spotify Downloader

## Overview

This Python script allows you to download songs from Spotify playlists and automatically add them to your local music library. It utilizes the Spotify API, YouTube, and other libraries to search for songs, download them, and update their metadata.

## Prerequisites

Before using this script, you need to set up a few things:

1. **Spotify API Credentials**: Obtain your Spotify API client ID and client secret.
2. **Environment Variables**: Store your Spotify API credentials in a `.env` file.
3. **Dependencies**: Install the required Python libraries listed in `requirements.txt`.

## Features

- Download all songs from Spotify playlists.
- Add unsynced lyrics to downloaded audio.
- Embed metadata such as artist name, album name, release date, and album art into downloaded songs.
- Automatically add downloaded songs to your local music library.

## Usage

1. Set up your environment by installing dependencies and configuring environment variables.
2. Configure the `outputPath` variable in the script.
3. Edit the playlist link in the script.
4. Run the script.
5. The script will get songs from the playlist(s), search for them on YouTube, download them as MP3s, and embed metadata.
6. Finally, it will move the downloaded songs to the specified location in your local music library (default: disabled).

## Configuration

- **Logging**: Configure logging settings in `spotify_downloader.log`.
- **Language Mapping**: Customize language mappings in the `languageMapping` dictionary.
- **Output Path**: Specify the output directory for downloaded songs in `outputPath`.

## Error Handling

The script includes robust error handling mechanisms to handle various edge cases gracefully. It logs informative error messages to `spotify_downloader.log` for troubleshooting.

## Contributing

Contributions are welcome! Feel free to fork the repository, make improvements, and submit pull requests.
