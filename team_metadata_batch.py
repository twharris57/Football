import requests


import requests
import json
import nfl_data_py as nfl

# Replace with your OpenWeatherMap API key
api_key = 'YOUR_API_KEY'

# Function to get altitude of a stadium
def get_stadium_altitude(city):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
    response = requests.get(url)
    data = response.json()
    if response.status_code == 200:
        return data['coord']['lat']  # Approximate altitude can be derived from latitude
    else:
        return None

# Function to determine play preference based on team stats
def get_play_preference(team):
    # Placeholder logic for determining play preference
    # This should be replaced with actual logic based on team stats
    if team in ['Kansas City Chiefs', 'Los Angeles Chargers']:
        return 'passing'
    elif team in ['Baltimore Ravens', 'Tennessee Titans']:
        return 'rushing'
    else:
        return 'balanced'

# Function to determine temperature accustomment
def get_temperature_accustomment(city):
    # Geocoding API to get latitude and longitude
    geocode_url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
    geocode_response = requests.get(geocode_url)
    
    if geocode_response.status_code != 200:
        return 'none'  # Unable to get location data

    geocode_data = geocode_response.json()
    lat = geocode_data['coord']['lat']
    lon = geocode_data['coord']['lon']
    
    # Historical weather data API
    historical_url = f"http://history.openweathermap.org/data/2.5/aggregated/year?lat={lat}&lon={lon}&appid={api_key}"
    historical_response = requests.get(historical_url)
    
    if historical_response.status_code != 200:
        return 'none'  # Unable to get historical data

    historical_data = historical_response.json()
    
    # Analyze temperature data
    average_temp = 0
    count = 0
    
    for day in historical_data['result']:
        average_temp += day['temp']['mean']  # Mean temperature in Kelvin
        count += 1

    if count == 0:
        return 'none'  # No data available

    average_temp /= count  # Calculate average temperature
    average_temp_fahrenheit = (average_temp - 273.15) * 9/5 + 32  # Convert to Fahrenheit

    if average_temp_fahrenheit > 75:
        return 'hot'
    elif average_temp_fahrenheit < 32:
        return 'cold'
    else:
        return 'none'

# Main function to gather team data
def gather_nfl_team_data():
    teams = nfl.teams()  # Get the list of NFL teams
    team_data = []

    for team in teams:
        team_info = {
            'team_name': team['abbreviation'],
            'home_stadium_altitude': get_stadium_altitude(team['city']),
            'play_preference': get_play_preference(team['full_name']),
            'temperature_accustomment': get_temperature_accustomment(team['city'])
        }
        team_data.append(team_info)

    return json.dumps(team_data, indent=4)

# Execute the function and print the result
if __name__ == "__main__":
    nfl_team_data = gather_nfl_team_data()
    print(nfl_team_data)



