entity_id = data.get("entity_id")
state = data.get("state")
fan_mode = data.get("fan_mode")
temperature = data.get("temperature")

if entity_id:
    current = hass.states.get(entity_id)
    if current:
        new_state = state if state else current.state
        attributes = current.attributes.copy()
        
        if fan_mode:
            attributes["fan_mode"] = fan_mode
        if temperature:
            attributes["temperature"] = float(temperature)
            
        hass.states.set(entity_id, new_state, attributes)