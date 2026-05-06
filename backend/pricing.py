def calculate_retail_price(cny_cost: float, exchange_rate: float, margin_pct: float = None, markup_multiplier: float = None) -> float:
    """
    Dynamically converts base CNY cost to EUR using the current exchange rate,
    then applies a configurable margin or markup to output the retail price.
    
    Args:
        cny_cost: Base cost in Chinese Yuan.
        exchange_rate: The CNY to EUR exchange rate.
        margin_pct: Target margin percentage (e.g., 60 for 60% margin).
        markup_multiplier: Target multiplier (e.g., 2.5 for 2.5x cost).
        
    Returns:
        float: The calculated retail price in EUR, rounded to 2 decimal places.
    """
    cost_eur = cny_cost * exchange_rate
    
    if markup_multiplier is not None:
        retail_price = cost_eur * markup_multiplier
    elif margin_pct is not None:
        if margin_pct >= 100:
            raise ValueError("margin_pct must be less than 100")
        if margin_pct < 0:
            retail_price = cost_eur
        else:
            retail_price = cost_eur / (1.0 - (margin_pct / 100.0))
    else:
        retail_price = cost_eur
        
    return round(retail_price, 2)
