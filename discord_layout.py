"""Small spacing between embed sections without extra visible fields."""
GAP = '\n\u200b'


def space_headings(embed, *, space_first=True):
    if not embed.fields:
        return embed
    description = embed.description or ''
    if space_first and not description.endswith(GAP):
        embed.description = description[:4096 - len(GAP)] + GAP
    for index, field in enumerate(embed.fields[:-1]):
        if not field.value.endswith(GAP):
            embed.set_field_at(index, name=field.name, value=field.value[:1024 - len(GAP)] + GAP, inline=field.inline)
    return embed
