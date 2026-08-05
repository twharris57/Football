import nfl_data_py as nfl
import numpy as np

def get_games_for_week(year, week):
    """Gets a list of games for a given NFL week."""

    df = nfl.import_schedules(years=[year])
    week_games = df[df['week'] == week]

    return week_games[['home_team', 'away_team', 'game_type', 'gameday', 'home_spread_odds', 'home_moneyline', 'away_spread_odds', 'away_moneyline', 'spread_line']]

def get_injuries(year, week):
    """Gets the injuries for a given NFL week"""
    df = nfl.import_injuries(years=[year])
    week_injuries = df[df['week'] == week]

    return week_injuries[week_injuries['report_primary_injury'].notnull()]

year = 2025
week = 1
gamedays = ['2025-09-07', '2025-09-08']

games = get_games_for_week(year, week)
games = games[games['gameday'].isin(gamedays)]

#rank the teams N..1 descending order based on home_moneyline
games = games.sort_values(by='home_moneyline', key=abs, ascending=False)
games.insert(0, 'points', range(len(games), 0, -1))

#pick whichever team the home moneyline thinks will win
games.insert(1, 'pick', 'NA')
games['pick'] = games.apply(lambda row: row['away_team'] if row['home_moneyline'] > 0 else row['home_team'], axis = 1)

#print the picks
print(games[['points', 'pick', 'home_team', 'away_team', 'home_spread_odds', 'home_moneyline', 'away_moneyline', 'home_spread_odds', 'away_spread_odds', 'spread_line', 'gameday', 'game_type']])
print()
toss_ups = games[games['home_moneyline'].abs() < 150]

if week > 1:
    #INJURY REPORT
    injuries = get_injuries(year, week)

    #All Injuries
    #print(injuries[['team', 'week', 'position', 'full_name', 'report_primary_injury', 'report_secondary_injury', 'report_status', 'date_modified']])

    #Filter to just teams playing
    injuries = injuries[injuries['team'].isin(np.concatenate([games['home_team'], games['away_team']]))]
    if len(injuries) > 0:
        #print(injuries[['team', 'week', 'position', 'full_name', 'report_primary_injury', 'report_secondary_injury', 'report_status', 'date_modified']])
        for tossup_idx in toss_ups.index:
            print(f"Toss up: {toss_ups['home_team'][tossup_idx]} (home) vs {toss_ups['away_team'][tossup_idx]} (away)")
            impactful_injuries = injuries[injuries['team'].isin([toss_ups['home_team'][tossup_idx], toss_ups['away_team'][tossup_idx]])]
            print(impactful_injuries[['team', 'week', 'position', 'full_name', 'report_primary_injury', 'report_secondary_injury', 'report_status', 'date_modified']])
            test = True

    else:
        print("NO INJURIES CURRENTLY REPORTED FOR TEAMS PLAYING THIS WEEKEND")
else:
    print("NO INJURIES CURRENTLY REPORTED FOR TEAMS PLAYING THIS WEEKEND")

test = True
#TODO: SENTIMENT ANALYSIS