def generate_round_robin(teams):
    """
    Generates a round-robin schedule for a list of teams using the circle method.
    Returns a list of rounds, where each round is a list of (team1, team2) matches.
    If the number of teams is odd, a 'BYE' placeholder is added.
    """
    teams = teams.copy()

    # If odd number of teams, add a BYE so everyone has a partner
    if len(teams) % 2 != 0:
        teams.append("BYE")

    num_teams = len(teams)
    num_rounds = num_teams - 1
    half = num_teams // 2

    rounds = []

    # Keep the first team fixed, rotate the rest
    fixed = teams[0]
    rotating = teams[1:]

    for round_num in range(num_rounds):
        round_matches = []

        # Build this round's team order: fixed team + rotating list
        current_order = [fixed] + rotating

        # Pair them up: first half vs second half (reversed)
        for i in range(half):
            team1 = current_order[i]
            team2 = current_order[num_teams - 1 - i]

            # Skip the match entirely if either team is the BYE
            if team1 != "BYE" and team2 != "BYE":
                round_matches.append((team1, team2))
            elif team1 == "BYE":
                round_matches.append((team2, "BYE"))  # team2 sits out this round
            else:
                round_matches.append((team1, "BYE"))  # team1 sits out this round

        rounds.append(round_matches)

        # Rotate: move the last team in 'rotating' to the front
        rotating = [rotating[-1]] + rotating[:-1]

    return rounds


def split_into_groups(teams, num_groups):
    """
    Splits a list of teams into `num_groups` roughly equal groups.
    Distributes teams one by one into each group in turn (like dealing cards),
    so group sizes differ by at most 1.
    """
    groups = [[] for _ in range(num_groups)]
    for index, team in enumerate(teams):
        group_index = index % num_groups
        groups[group_index].append(team)
    return groups


# ---------- Quick test ----------
if __name__ == "__main__":
    print("=== Test 1: Round robin with 4 teams ===")
    teams_4 = ["Team A", "Team B", "Team C", "Team D"]
    schedule = generate_round_robin(teams_4)
    for i, round_matches in enumerate(schedule, start=1):
        print(f"Round {i}:")
        for match in round_matches:
            print(f"   {match[0]} vs {match[1]}")

    print("\n=== Test 2: Round robin with 5 teams (odd, needs BYE) ===")
    teams_5 = ["Team A", "Team B", "Team C", "Team D", "Team E"]
    schedule_5 = generate_round_robin(teams_5)
    for i, round_matches in enumerate(schedule_5, start=1):
        print(f"Round {i}:")
        for match in round_matches:
            print(f"   {match[0]} vs {match[1]}")

    print("\n=== Test 3: Splitting 8 teams into 2 groups ===")
    teams_8 = [f"Team {i}" for i in range(1, 9)]
    groups = split_into_groups(teams_8, 2)
    for i, group in enumerate(groups, start=1):
        print(f"Group {chr(64 + i)}: {group}")