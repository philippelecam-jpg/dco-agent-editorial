"""Local configuration check: no provider calls and no secret values printed."""
import json, os
from urllib.parse import urlsplit
from .worker import configuration

def check():
    errors=[]
    base=os.getenv('PUBLIC_BASE_URL','')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        errors.append('PUBLIC_BASE_URL doit être une origine HTTPS sans chemin ni slash final.')
    if os.getenv('YOUTUBE_PRIVACY') not in ('unlisted','public'):
        errors.append('YOUTUBE_PRIVACY doit être unlisted ou public pour livrer le lien au prospect.')
    if len(os.getenv('ADMIN_TOKEN',''))<32: errors.append('ADMIN_TOKEN doit contenir au moins 32 caractères aléatoires.')
    try:
        if not 1<=int(os.getenv('MAX_DAILY_REQUESTS','10'))<=100: raise ValueError
    except ValueError: errors.append('MAX_DAILY_REQUESTS doit être compris entre 1 et 100.')
    return {'missing_configuration':configuration(),'errors':errors}

if __name__=='__main__':
    result=check(); print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(1 if result['missing_configuration'] or result['errors'] else 0)
