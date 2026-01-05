import random

# -----------------------------------------------------------------------------
# GAME LOGIC UTILITIES
# -----------------------------------------------------------------------------
def resolve_round_logic(p1_card, p2_card, current_pot):
    """
    Returns (p1_points, p2_points, is_tie)
    """
    if p1_card > p2_card:
        return current_pot, 0, False
    elif p2_card > p1_card:
        return 0, current_pot, False
    else:
        return 0, 0, True

# -----------------------------------------------------------------------------
# SUPER INTELLIGENT BOT LOGIC (SmartBot)
# -----------------------------------------------------------------------------
class SmartBot:
    def __init__(self):
        self.name = "DeepGoof"
        # Memory of opponent's past moves relative to prize value
        self.opponent_history = {i: [] for i in range(1, 14)}

    def record_move(self, prize_card, opponent_move):
        self.opponent_history[prize_card].append(opponent_move)

    def decide_move(self, bot_hand, player_hand, current_pot_value, remaining_prizes, bot_score, player_score):
        """
        Decides the best move using either Minimax (Endgame) or Heuristic (Early Game).
        """
        # 1. ENDGAME SOLVER: If state space is small, solve perfectly using recursion.
        if len(bot_hand) <= 6:
            return self.minimax_move(bot_hand, player_hand, current_pot_value, remaining_prizes, bot_score, player_score)
        
        # 2. PROBABILISTIC STRATEGY: Use heuristic payoff matrix for speed in early game.
        return self.heuristic_move(bot_hand, player_hand, current_pot_value)

    def minimax_move(self, bot_hand, player_hand, current_pot, remaining_prizes, bot_score, player_score):
        """ Recursive Minimax to find the optimal move assuming perfect play from opponent. """
        best_card = bot_hand[0]
        max_min_utility = -float('inf') 
        depth_limit = 99 if len(bot_hand) <= 4 else 1
        candidates = sorted(bot_hand, reverse=True)
        best_options = []

        for b in candidates:
            min_utility = float('inf') 
            for p in player_hand:
                b_won, p_won, is_tie = resolve_round_logic(b, p, current_pot)
                current_diff = b_won - p_won
                future_diff = 0
                if remaining_prizes:
                    new_b = [x for x in bot_hand if x != b]
                    new_p = [x for x in player_hand if x != p]
                    future_diff = (sum(new_b) - sum(new_p))
                
                if is_tie and not remaining_prizes: current_diff = 0 
                total_outcome = (bot_score - player_score) + current_diff + future_diff
                if total_outcome < min_utility: min_utility = total_outcome
            
            if min_utility > max_min_utility:
                max_min_utility = min_utility
                best_options = [b]
            elif min_utility == max_min_utility:
                best_options.append(b)
        
        return random.choice(best_options)

    def heuristic_move(self, bot_hand, player_hand, current_pot):
        """ Calculates Expected Value (EV) based on predicted opponent moves. """
        # Predict opponent based on pot
        effective_val = min(current_pot, 15)
        total_w = 0
        weights = {}
        for c in player_hand:
            w = 1.0
            if current_pot > 10:
                if c >= max(player_hand) - 1: w += 3.0
                if c < 5: w *= 0.1
            else:
                if abs(c - effective_val) <= 1: w += 2.0
            weights[c] = w
            total_w += w
            
        best_card = bot_hand[0]
        best_ev = -float('inf')
        
        for my_card in bot_hand:
            ev = 0
            for opp_card in player_hand:
                prob = weights[opp_card]/total_w
                b_pts, p_pts, is_tie = resolve_round_logic(my_card, opp_card, current_pot)
                cost = my_card
                u = -(cost*0.9) if is_tie else (b_pts - p_pts) - (cost*0.8)
                ev += u * prob
            ev += random.uniform(-0.1, 0.1)
            if ev > best_ev:
                best_ev = ev
                best_card = my_card
        return best_card

# -----------------------------------------------------------------------------
# MULTIPLAYER GAME ENGINE
# -----------------------------------------------------------------------------
class BidWiserGame:
    def __init__(self, human_players):
        """
        human_players: List of names.
        If len=1, Player 2 is Bot.
        If len=2, Player 2 is human.
        """
        self.prizes = list(range(1, 14))
        random.shuffle(self.prizes)
        
        # Player 1 (Host)
        self.p1_name = human_players[0]
        self.p1_hand = list(range(1, 14))
        self.p1_score = 0
        self.p1_move = None # Waiting for move

        # Player 2 (Human or Bot)
        if len(human_players) > 1:
            self.p2_name = human_players[1]
            self.p2_is_bot = False
            self.bot = None
        else:
            self.p2_name = "DeepGoof (Bot)"
            self.p2_is_bot = True
            self.bot = SmartBot()
            
        self.p2_hand = list(range(1, 14))
        self.p2_score = 0
        self.p2_move = None # Waiting for move
        
        self.carry_over_pot = 0
        self.round_history = []
        self.current_prize = self.prizes.pop(0)
        self.game_over = False

    def get_state(self):
        return {
            'current_prize': self.current_prize,
            'carry_over': self.carry_over_pot,
            'total_pot': self.current_prize + self.carry_over_pot,
            'p1': {
                'name': self.p1_name, 
                'score': self.p1_score, 
                'hand': self.p1_hand, 
                'has_moved': self.p1_move is not None
            },
            'p2': {
                'name': self.p2_name, 
                'score': self.p2_score, 
                'hand': self.p2_hand, # EXPOSED SO HUMAN P2 CAN SEE IT
                'hand_count': len(self.p2_hand),
                'has_moved': self.p2_move is not None,
                'is_bot': self.p2_is_bot
            },
            'history': self.round_history,
            'game_over': self.game_over
        }

    def register_move(self, player_name, card):
        """ 
        Stores a move. Returns True if logic updated (either round resolved or just waiting).
        """
        if self.game_over: return False
        
        # Identify who moved
        if player_name == self.p1_name:
            if card in self.p1_hand: self.p1_move = card
        elif player_name == self.p2_name and not self.p2_is_bot:
            if card in self.p2_hand: self.p2_move = card
            
        # Check if P2 is Bot. If P1 has moved, Bot moves instantly.
        if self.p2_is_bot and self.p1_move is not None:
             pot_val = self.current_prize + self.carry_over_pot
             self.p2_move = self.bot.decide_move(
                self.p2_hand, self.p1_hand, pot_val, 
                list(self.prizes), self.p2_score, self.p1_score
             )
             self.bot.record_move(self.current_prize, self.p1_move)

        # If both moved, resolve
        if self.p1_move is not None and self.p2_move is not None:
            self.resolve_round()
            return True 
            
        return True 

    def resolve_round(self):
        p1_card = self.p1_move
        p2_card = self.p2_move
        pot_val = self.current_prize + self.carry_over_pot
        
        # Remove cards
        if p1_card in self.p1_hand: self.p1_hand.remove(p1_card)
        if p2_card in self.p2_hand: self.p2_hand.remove(p2_card)
        
        # Determine Winner
        p1_pts, p2_pts, is_tie = resolve_round_logic(p1_card, p2_card, pot_val)
        
        result = "Tie"
        if not is_tie:
            if p1_pts > 0:
                self.p1_score += p1_pts
                self.carry_over_pot = 0
                result = f"{self.p1_name} Wins"
            else:
                self.p2_score += p2_pts
                self.carry_over_pot = 0
                result = f"{self.p2_name} Wins"
        else:
            self.carry_over_pot += self.current_prize
            if not self.prizes: # Split last
                split = pot_val / 2.0
                self.p1_score += split
                self.p2_score += split
                self.carry_over_pot = 0
                result = "Split"
        
        self.round_history.append({
            'prize': self.current_prize,
            'p1_card': p1_card,
            'p2_card': p2_card,
            'result': result
        })
        
        # Reset moves for next round
        self.p1_move = None
        self.p2_move = None
        
        if not self.prizes:
            self.game_over = True
            self.current_prize = 0
        else:
            self.current_prize = self.prizes.pop(0)