import random
import math

# -----------------------------------------------------------------------------
# MATH & STRATEGY UTILITIES
# -----------------------------------------------------------------------------
def calculate_score(cards):
    """ 
    Standard No Thanks scoring: 
    Sum of cards, but in a run (e.g., 23, 24, 25), only the lowest card (23) counts.
    """
    if not cards: return 0
    sorted_cards = sorted(cards)
    score = 0
    previous = -1
    for card in sorted_cards:
        # If this card is NOT a direct follower of the previous one, it adds points.
        if card != previous + 1:
            score += card
        previous = card
    return score

def get_run_equity(card, hand, deck_size, visible_cards):
    """
    Calculates the 'Probability Equity' of a card.
    Equity represents the "Future Value" of connecting a run.
    """
    # 1. Immediate Neighbors check
    neighbors = [card - 1, card + 1]
    equity = 0.0
    
    for n in neighbors:
        if n in hand:
            # We already have the neighbor. HUGE value.
            # Connecting 22 and 24 with a 23 is worth 24 points (saves the 24).
            equity += 15.0 
        elif n in visible_cards:
            # Neighbor is dead (someone else has it). No future equity.
            equity -= 2.0
        else:
            # Neighbor is hidden (in deck or removed).
            # Hypergeometric Probability check.
            unknowns = deck_size + 9 # 9 cards are always removed in No Thanks
            
            # Chance it is NOT in the removed pile
            prob_in_play = 1.0 - (9.0 / float(unknowns) if unknowns > 0 else 0)
            
            # Value of a connector is roughly half the face value of the card it saves
            equity += (n * 0.4) * prob_in_play
            
    return equity

def predict_opponent_action(opponent_dict, card, projected_pot):
    """
    Estimates the probability (0.0 to 1.0) that an opponent takes the card.
    Used for 'Orbit Simulation' to see if the card will come back to us.
    """
    if opponent_dict['chips'] == 0: return 1.0 # Forced take (Bankrupt)
    
    # Does it fit their hand?
    opp_score = calculate_score(opponent_dict['cards'])
    opp_new_score = calculate_score(opponent_dict['cards'] + [card])
    
    # If it lowers their score, they WANT it.
    if opp_new_score < opp_score:
        # But will they pass to be greedy?
        # If they have lots of chips, maybe. If low chips, they take instantly.
        if opponent_dict['chips'] < 3: return 1.0
        return 0.8 # High chance they take
        
    # Chip Desperation
    # If they are broke and the pot has chips, they might take junk just to survive.
    if opponent_dict['chips'] <= 2 and projected_pot >= 3:
        return 0.9 # Survival Mode
        
    # Pot Value Math
    # If the Pot has so many chips it covers half the card's points, it's tempting.
    if projected_pot > (card / 2):
        return 0.6 
        
    return 0.1 # Likely Pass

# -----------------------------------------------------------------------------
# MAIN GAME ENGINE
# -----------------------------------------------------------------------------
class PickPassGame:
    def __init__(self, human_players):
        """
        human_players: List of names ['Ankit', 'John', 'Sarah']
        """
        self.min_card = 3
        self.max_card = 35
        self.cards_removed = 9
        self.start_chips = 11
        
        self.players = []
        
        # 1. Add Humans
        for name in human_players:
            self.players.append({'name': name, 'cards': [], 'chips': self.start_chips, 'is_human': True})
            
        # 2. Fill with Bots (Target 5 players total)
        bot_names = ["Vector", "Matrix", "Tensor", "Scalar", "Logit"]
        needed = 5 - len(self.players)
        
        # If we have less than 5 humans, fill the rest with bots
        if needed > 0:
            for i in range(needed):
                # Ensure we don't run out of bot names if many bots needed
                b_name = bot_names[i] if i < len(bot_names) else f"Bot-{i}"
                self.players.append({'name': b_name, 'cards': [], 'chips': self.start_chips, 'is_human': False})
            
        # Setup Deck
        full_deck = list(range(self.min_card, self.max_card + 1))
        random.shuffle(full_deck)
        self.deck = full_deck[self.cards_removed:]
        
        self.pot = 0
        self.current_card = self.deck.pop(0)
        # Random starting player
        self.current_player_idx = random.randint(0, len(self.players) - 1)
        self.game_over = False
        self.leaderboard = [] # Stores final stats when game ends

    def get_state(self):
        """ Returns the current game state to be sent to the frontend via SocketIO """
        return {
            'pot': self.pot,
            'current_card': self.current_card,
            'current_player': self.current_player_idx,
            'current_player_name': self.players[self.current_player_idx]['name'],
            'deck_count': len(self.deck),
            'game_over': self.game_over,
            'players': self.players,
            'leaderboard': self.leaderboard
        }

    def bot_move(self):
        """
        Executes the intelligent decision matrix for the current bot.
        Returns: True (Take) or False (Pass)
        """
        me = self.players[self.current_player_idx]
        
        # Safety Check: If it's a human, this function shouldn't be running logic
        if me['is_human']: return False
        
        card = self.current_card
        
        # 1. CRITICAL: ZERO CHIPS
        if me['chips'] == 0:
            return True # Forced take

        # 2. CALCULATE "REAL COST"
        # The cost is not just points. It's Points - Chips gained.
        current_score = calculate_score(me['cards'])
        new_score = calculate_score(me['cards'] + [card])
        point_delta = new_score - current_score
        
        # Chip Value Multiplier (Diminishing Returns)
        # A chip is worth 3 points if you are broke, 1 point if you are rich.
        chip_value = 1.0 + (12.0 / (me['chips'] + 1))
        
        # "Economic Cost" of taking NOW
        economic_impact = point_delta - (self.pot * chip_value)
        
        # 3. CALCULATE "FUTURE EQUITY" (The Gap Analysis)
        # Gather visible cards from all players to know what's dead
        visible_cards = set()
        for p in self.players:
            for c in p['cards']: visible_cards.add(c)
            
        gap_bonus = get_run_equity(card, me['cards'], len(self.deck), visible_cards)
        
        # The Adjusted Cost of the card considering future luck
        adjusted_cost = economic_impact - gap_bonus

        # 4. ORBIT SIMULATION (The "Next Player" Logic)
        # If I pass, what is the probability the card returns to me?
        prob_card_dies = 0.0
        my_seat = self.current_player_idx
        num_players = len(self.players)
        
        # Check opponents in order
        for i in range(1, num_players):
            seat = (my_seat + i) % num_players
            opponent = self.players[seat]
            
            # Predict Opponent Take Probability
            p_take = predict_opponent_action(opponent, card, self.pot + i)
            
            # Aggregate risk: The card must survive ALL previous opponents to survive this one
            prob_survived_until_here = (1.0 - prob_card_dies)
            prob_card_dies += prob_survived_until_here * p_take

        prob_return = 1.0 - prob_card_dies
        
        # 5. COMPARATIVE UTILITY ANALYSIS
        # Utility of taking NOW
        u_take = -adjusted_cost
        
        # Utility of PASSING
        # If returns: We get card + N chips.
        future_pot = self.pot + num_players
        economic_impact_future = point_delta - (future_pot * chip_value)
        u_return = -(economic_impact_future - gap_bonus)
        
        # If dies: We lose 1 chip (painful based on chip_value)
        u_loss = -(1.0 * chip_value) 
        
        u_pass = (u_return * prob_return) + (u_loss * prob_card_dies)
        
        # 6. FINAL THRESHOLDS with Greed Bias
        # If we have plenty of chips, we prefer passing to milk the table.
        greed_bias = 0
        if me['chips'] > 8: greed_bias = 3.0
        
        diff = u_take - (u_pass - greed_bias)
        
        return diff > 0

    def play_turn(self, action, player_name_check=None):
        """
        Executes the move.
        player_name_check: Used to ensure only the active player can move.
        """
        current_p = self.players[self.current_player_idx]
        
        # Security: Prevent Player B from moving when it's Player A's turn
        if player_name_check and current_p['name'] != player_name_check:
            # Ignore the input if it's not their turn
            return self.get_state()
            
        if action == 'take':
            current_p['cards'].append(self.current_card)
            current_p['chips'] += self.pot
            self.pot = 0
            
            # Rule: Turn passes to NEXT player
            self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
            
            if not self.deck:
                self.end_game()
            else:
                self.current_card = self.deck.pop(0)

        elif action == 'pass':
            if current_p['chips'] > 0:
                current_p['chips'] -= 1
                self.pot += 1
                self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
            else:
                # Forced take if logic failed (security check)
                return self.play_turn('take')
        
        return self.get_state()

    def end_game(self):
        """ Calculates final scores and generates the detailed leaderboard. """
        self.game_over = True
        self.leaderboard = []
        for p in self.players:
            card_total = calculate_score(p['cards'])
            final_score = card_total - p['chips']
            
            self.leaderboard.append({
                'name': p['name'],
                'card_total': card_total,
                'chips': p['chips'],
                'final_score': final_score,
                'is_human': p['is_human']
            })
            
        # Sort by final score (Lowest is best in No Thanks)
        self.leaderboard.sort(key=lambda x: x['final_score'])