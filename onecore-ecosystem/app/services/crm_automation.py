import re
from fastapi import HTTPException

FIELDS={"full_name","email","phone","company"}
OPS={"eq","ne","contains","starts_with","ends_with","is_set","in"}


def validate_segment_filters(node,depth=0):
    if depth>3 or not isinstance(node,dict):
        raise HTTPException(422,"Audience filters may contain at most three nested groups")
    if set(node)=={"logic","conditions"}:
        logic=node["logic"]
        conditions=node["conditions"]
        if logic not in {"and","or"} or not isinstance(conditions,list) or len(conditions)>20:
            raise HTTPException(422,"Each audience group needs AND/OR and 1–20 conditions")
        for item in conditions:
            validate_segment_filters(item,depth+1)
        return
    if set(node)!={"field","op","value"} or node["field"] not in FIELDS or node["op"] not in OPS:
        raise HTTPException(422,"Unsupported audience field or operator")
    value=node["value"]
    if node["op"]=="is_set":
        if value not in (True,False):
            raise HTTPException(422,"is_set requires a boolean value")
    elif node["op"]=="in":
        if not isinstance(value,list) or not 1<=len(value)<=20 or any(not isinstance(x,str) or len(x)>180 for x in value):
            raise HTTPException(422,"in requires 1–20 text values")
    elif not isinstance(value,str) or len(value)>180:
        raise HTTPException(422,"Audience comparison values must be text up to 180 characters")


def matches_segment(contact,filters):
    if not filters or filters=={"logic":"and","conditions":[]}:
        return True
    if "logic" in filters:
        values=[matches_segment(contact,item) for item in filters["conditions"]]
        return all(values) if filters["logic"]=="and" else any(values)
    raw=getattr(contact,filters["field"],None)
    value="" if raw is None else str(raw)
    expected=filters["value"]
    op=filters["op"]
    if op=="is_set": result=bool(value.strip()) if isinstance(value,str) else raw is not None
    elif op=="eq": result=value.casefold()==expected.casefold()
    elif op=="ne": result=value.casefold()!=expected.casefold()
    elif op=="contains": result=expected.casefold() in value.casefold()
    elif op=="starts_with": result=value.casefold().startswith(expected.casefold())
    elif op=="ends_with": result=value.casefold().endswith(expected.casefold())
    elif op=="in": result=value.casefold() in {x.casefold() for x in expected}
    else: result=False
    return result


TEMPLATE_VARIABLES={"first_name","last_name","full_name","email","phone","company","campaign_name"}

def validate_template_content(subject,body):
    for text in (subject or "",body or ""):
        for variable in re.findall(r"{{\\s*([a-z_]+)\\s*}}",text):
            if variable not in TEMPLATE_VARIABLES:
                raise HTTPException(422,"Unsupported template variable: "+variable)
