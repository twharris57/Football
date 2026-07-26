import nfl_data_py as nfl
import pandas as pd

debug = True

# Define weights for each weighting function
weight_factors = {
    'compute_vegas_odds': 1.0,
    #'compute_injury_impact': 1.5,  # Example weight for injury analysis
    # Add other weighting functions and their weights here
}

def main():
    gamedays = ['2026-01-03', '2026-01-04']
    games = get_games_for_week(gamedays)
    
    weight_functions = [compute_vegas_odds] #compute_injury_impact
    weight_results = []

    for weight_function in weight_functions:
        result = weight_function(games)
        weight_results.append((weight_function.__name__, result))

    results = calc_results(weight_results, games)
    print_results(results)

def get_games_for_week(gamedays):
    """Gets a list of games scheduled for the supplied list of days."""
    df = nfl.import_schedules(years=[2025])
    week_games = df[df['gameday'].isin(gamedays)]
    return week_games[['home_team', 'away_team', 'home_moneyline', 'away_moneyline']]

def compute_probability(moneyline):
    """Converts moneyline to implied probability."""
    if moneyline > 0:
        return 100 / (moneyline + 100)
    else:
        return abs(moneyline) / (abs(moneyline) + 100)

### WEIGHT FUNCTIONS ###
def compute_vegas_odds(games):
    """Generates weighted results based on home_moneyline."""
    weights = {}
    for index, row in games.iterrows():
        home_moneyline = row['home_moneyline']
        away_moneyline = row['away_moneyline']
        
        home_probability = compute_probability(home_moneyline)
        away_probability = compute_probability(away_moneyline)

        # Normalize probabilities to ensure they sum to 1
        total_probability = home_probability + away_probability
        if total_probability > 0:
            home_probability /= total_probability
            away_probability /= total_probability

        # Calculate confidence as the difference between home and away probabilities
        confidence = home_probability - away_probability
        weights[f"{row['away_team']} at {row['home_team']}"] = confidence
        
        if debug:
            print(f"PREDICTION: {row['away_team']} at {row['home_team']}: confidence {confidence:.4f}, "
                  f"home_probability {home_probability:.4f}, away_probability {away_probability:.4f}, "
                  f"home_moneyline {home_moneyline}, away_moneyline {away_moneyline}")

    return weights

#https://duckduckgo.com/?q=DuckDuckGo+AI+Chat&ia=chat&duckai=1
# def get_team_attributes(team):
#     """Retrieves the playing style and temperature bias for a given team."""
#     # Example data retrieval (you may need to adjust based on actual data structure)
#     team_stats = nfl.import_team_stats(years=[2025])  # Adjust the year as needed
#     team_weather_data = nfl.import_weather_data(years=[2025])  # Placeholder for weather data

#     # Get the team's stats
#     team_data = team_stats[team_stats['team'] == team].iloc[0]

#     # Determine playing style
#     passing_yards = team_data['passing_yards']
#     rushing_yards = team_data['rushing_yards']
    
#     if passing_yards > rushing_yards:
#         style = 'passing'
#     else:
#         style = 'rushing'

#     # Determine temperature bias (this is a placeholder logic)
#     # You may need to implement a more sophisticated method to determine bias
#     if team in team_weather_data['hot_teams'].values:
#         temp_bias = 'hot'
#     elif team in team_weather_data['cold_teams'].values:
#         temp_bias = 'cold'
#     else:
#         temp_bias = 'none'

#     return style, temp_bias

# def compute_adverse_conditions(games):
#     """Generates weighted results based on adverse conditions."""
#     weights = {}
    
#     for index, row in games.iterrows():
#         home_team = row['home_team']
#         away_team = row['away_team']
        
#         # Get team attributes
#         home_style, home_temp_bias = get_team_attributes(home_team)
#         away_style, away_temp_bias = get_team_attributes(away_team)
        
#         # Initialize weight for the game
#         weight = 0
        
#         # Example conditions (you'll need to replace these with actual data)
#         conditions = {
#             'kickoff_temperature': 85,  # Expected temperature at kickoff at the home stadium
#             'home_team_temp_bias': home_temp_bias,
#             'away_team_temp_bias': away_temp_bias,
#             'altitude': {'home': 5280, 'away': 1000},  # Example altitudes in feet
#             'windy': True,  # Example condition
#             'wet': False,   # Example condition
#             'home_team_style': home_style,
#             'away_team_style': away_style
#         }
        
#         # Temperature condition checks
#         if conditions['kickoff_temperature'] > 80:
#             if conditions['home_team_temp_bias'] == 'hot' and conditions['away_team_temp_bias'] == 'cold':
#                 weight += 0.1  # Bonus for home team in extreme heat
#             elif conditions['home_team_temp_bias'] == 'cold' and conditions['away_team_temp_bias'] == 'hot':
#                 weight -= 0.1  # Penalty for home team in extreme heat

#         elif conditions['kickoff_temperature'] < 70:
#             if conditions['home_team_temp_bias'] == 'cold' and conditions['away_team_temp_bias'] == 'hot':
#                 weight -= 0.1  # Penalty for home team in extreme cold
#             elif conditions['home_team_temp_bias'] == 'hot' and conditions['away_team_temp_bias'] == 'cold':
#                 weight += 0.1  # Bonus for home team in extreme cold

#         # Altitude condition (adjusted for 1000 feet difference)
#         altitude_difference = conditions['altitude']['home'] - conditions['altitude']['away']
#         if altitude_difference >= 1000:
#             weight += 0.2  # Bonus for high altitude team at low altitude
#         elif altitude_difference <= -1000:
#             weight -= 0.1  # Penalty for low altitude team at high altitude

#         # Windy or wet conditions
#         if conditions['windy'] and conditions['home_team_style'] == 'passing' and conditions['away_team_style'] == 'rushing':
#             weight -= 0.1  # Penalty for passing team in windy conditions
#         if conditions['wet'] and conditions['home_team_style'] == '




#example additional weight function
# def compute_injury_impact(games):
#     """Generates weighted results based on player injuries."""
#     weights = {}
#     injuries = get_injuries()  # Assume this function retrieves injury data

#     for index, row in games.iterrows():
#         home_team = row['home_team']
#         away_team = row['away_team']
        
#         # Analyze injuries for both teams
#         home_injuries = injuries[injuries['team'] == home_team]
#         away_injuries = injuries[injuries['team'] == away_team]

#         # Calculate impact based on injuries (this is a placeholder logic)
#         home_impact = len(home_injuries) * 0.1  # Example impact calculation
#         away_impact = len(away_injuries) * 0.1

#         # Calculate confidence based on injury impact
#         confidence = home_impact - away_impact
#         weights[f"{away_team} at {home_team}"] = confidence

#         if debug:
#             print(f"PREDICTION: {away_team} at {home_team}: injury confidence {confidence:.4f}, "
#                   f"home_injuries {len(home_injuries)}, away_injuries {len(away_injuries)}")

#     return weights


#IDEAS for additional weight functions
# - sentiment analysis
# - historic performance data
# - advanced metrics such as DVOA or EPA
# - weather
# - betting trends
# - player matchups
# - impact injury analysis
# - additional betting metrics such as spread or total points

def calc_results(weights, games):
    """Combines the lists of available weights into a single dict and sorts them."""
    combined_weights = {}
    
    for source_name, weight_dict in weights:
        for game, confidence in weight_dict.items():
            if game not in combined_weights:
                combined_weights[game] = {}
            # Apply weight factor for each source
            combined_weights[game][source_name] = confidence * weight_factors[source_name]
    
    for source_name, weight_dict in weights:
        for game, confidence in weight_dict.items():
            if game not in combined_weights:
                combined_weights[game] = {}
            combined_weights[game][source_name] = confidence  # Store confidence by source

    # Sort by absolute value of total confidence
    results = []
    for game, conf_dict in combined_weights.items():
        total_confidence = sum(conf_dict.values())
        predicted_winner = "Home" if total_confidence > 0 else "Away" if total_confidence < 0 else "Toss-up"
        
        # Prepare the result dictionary
        result = {
            'game_name': game,
            'predicted_winner': predicted_winner,
            'overall_confidence': total_confidence,
            'recommended_points': 0  # Placeholder for recommended points
        }
        
        # Add each source's confidence to the result
        for source in weights:
            source_name = source[0]
            result[source_name] = conf_dict.get(source_name, 0)  # Default to 0 if not present

        results.append(result)

    # Sort results by absolute value of overall confidence
    results.sort(key=lambda x: abs(x['overall_confidence']), reverse=True)

    # Assign recommended points
    for idx, result in enumerate(results):
        result['recommended_points'] = len(results) - idx  # N..1 descending

    return pd.DataFrame(results)

def calc_results_old(weights, games):
    """Combines the lists of available weights into a single dict and sorts them."""
    combined_weights = {}
    
    for source_name, weight_dict in weights:
        for game, confidence in weight_dict.items():
            if game not in combined_weights:
                combined_weights[game] = []
            combined_weights[game].append((confidence, source_name))

    # Sort by absolute value of confidence
    sorted_games = sorted(combined_weights.items(), key=lambda x: abs(sum(conf[0] for conf in x[1])), reverse=True)
    
    # Assign recommended points
    results = []
    for idx, (game, conf_list) in enumerate(sorted_games):
        total_confidence = sum(conf[0] for conf in conf_list)
        recommended_points = len(sorted_games) - idx  # N..1 descending
        predicted_winner = "Home" if total_confidence > 0 else "Away" if total_confidence < 0 else "Toss-up"
        
        results.append({
            'game_name': game,
            'predicted_winner': predicted_winner,
            'recommended_points': recommended_points,
            'overall_confidence': total_confidence,
            'confidence_sources': conf_list
        })

    return pd.DataFrame(results)

def print_results(results):
    """Prints the results to the console in a table format."""
    print(results.to_string(index=False))

if __name__ == "__main__":
    main()
