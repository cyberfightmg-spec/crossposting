def detect_type(update: dict) -> str:
    """Detect content type: text, slides (media_group), or photo."""
    post = update.get("channel_post", {})
    
    if "media_group" in post:
        return "slides"
    if "photo" in post:
        return "photo"
    if "text" in post:
        return "text"
    return "unknown"