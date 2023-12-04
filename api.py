import requests
import datetime
import time
import base64
import json

backup_file = "backup.txt"
direct_domain = 'direct.com'
tunneled_domain = 'tunnel.com'
login_token = 'token'
settings = {}
last_users = []

# region Converting tools


async def days2time(days):
    expiry = ((datetime.datetime.now() + datetime.timedelta(days)).timestamp())
    return int(expiry)


async def time2days(target_timestamp):
    current_timestamp = time.time()
    timestamp_diff = target_timestamp - current_timestamp
    days_remaining = timestamp_diff / (1000 * 60 * 60 * 24) * 1000
    return int(days_remaining)


async def gb2byte(gb):
    return int(gb * 1024 * 1024 * 1024)


async def byte2gb(byte):
    return round((byte / 1024 / 1024 / 1024), 2)


async def backup(results):
    with open(backup_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(results, indent=4))


# endregion


def load_settings() -> bool:
    global settings, direct_domain, tunneled_domain
    with open('settings.json', 'r', encoding="utf-8") as file:
        settings = json.load(file)
        direct_domain = settings['server']['direct_domain']
        tunneled_domain = settings['server']['tunneled_domain']
        send_login_request(settings['server']['username'], settings['server']['password'])
        if login_token:
            print("Login successful!")
            return True
        else:
            print("Login failed. Unable to obtain login token.")
    return False


def send_login_request(username, password):
    global login_token
    url = direct_domain + '/api/admin/token'
    data = {
        'username': username,
        'password': password
    }

    try:
        response = requests.post(url, data=data, headers={'Content-Type': 'application/x-www-form-urlencoded'})

        if response.status_code == 200:
            token = response.json().get('access_token')
            if token:
                login_token = token
            else:
                print("Login token not found in the response.")
        else:
            login_token = None
            print("Login failed. Status code:", response.status_code)
    except requests.RequestException as e:
        print("An error occurred:", e)


async def create_user(username, days, gb):
    send_login_request(settings['server']['username'], settings['server']['password'])
    expire = await days2time(days)
    data_limit = await gb2byte(gb)

    url = f'{direct_domain}/api/user'
    headers = {
        'Authorization': f'Bearer {login_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "username": username,
        "proxies": {
            "vless": {
            }
        },
        "inbounds": {
            "vless": [
                "VLESS + TCP + TLS"
            ]
        },
        "expire": expire,
        "data_limit": data_limit,
        "data_limit_reset_strategy": "no_reset"
    }

    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            data = response.json()
            global last_users
            last_users = []
            return tunneled_domain + data.get('subscription_url')
        else:
            print("Failed to create user. Status code:", response.status_code)
    except requests.RequestException as e:
        print("An error occurred:", e)


async def edit_user(username, days, gb):
    expire = await days2time(days)
    data_limit = await gb2byte(gb)

    url = f'{direct_domain}/api/user/{username}'
    headers = {
        'Authorization': f'Bearer {login_token}',
        'Content-Type': 'application/json'
    }
    data = {
        "expire": expire,
        "data_limit": data_limit,
        "status": "active"
    }

    try:
        response = requests.put(url, json=data, headers=headers)
        url = f'{direct_domain}/api/user/{username}/reset'
        reset = requests.post(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return tunneled_domain + data.get('subscription_url')
        else:
            print("Failed to create user. Status code:", response.status_code)
    except requests.RequestException as e:
        print("An error occurred:", e)


async def delete_user(username) -> bool:
    url = f'{direct_domain}/api/user/{username}'
    headers = {
        'Authorization': f'Bearer {login_token}',
        'Content-Type': 'application/json'
    }
    try:
        response = requests.delete(url, headers=headers)
        if response.status_code == 200:
            global last_users
            last_users = []
            return True
        else:
            print("Failed to delete user. Status code:", response.status_code)
            return False
    except requests.RequestException as e:
        print("An error occurred:", e)
        return False


async def get_users():
    url = direct_domain + '/api/users'
    headers = {
        'Authorization': f'Bearer {login_token}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    users = response.json().get('users')
    await backup(users)
    return users


async def get_user(username):
    send_login_request(settings['server']['username'], settings['server']['password'])
    url = f'{direct_domain}/api/user/{username}'
    headers = {
        'Authorization': f'Bearer {login_token}',
        'Content-Type': 'application/json'
    }
    response = requests.get(url, headers=headers)
    data = response.json()
    active = data.get('status')
    data_limit = data.get('data_limit')
    if active == 'active':
        status = True
    else:
        status = False
    if data_limit is None:
        data_limit = 0
    info = {
        'username': username,
        'uuid': data['proxies']['vmess'].get('id'),
        'expire': await time2days(data.get('expire')),
        'users': data.get('users'),
        'data_limit': await byte2gb(data_limit),
        'used_traffic': await byte2gb(data.get('used_traffic')),
        'remain': await byte2gb(data.get('data_limit') - data.get('used_traffic')),
        'percent': await byte2gb((data.get('data_limit') - data.get('used_traffic')) * 100 / data.get('data_limit')),
        'subscription_url': tunneled_domain + data.get('subscription_url'),
        'links': data.get('links'),
        'status': status
    }
    return info


async def find(target):
    global last_users
    if len(last_users) == 0:
        last_users = await get_users()
    items = []
    for user in last_users:
        username = user.get('username')
        if target.lower() in username.lower():
            items.append(username)
    return items


async def find_config(config):
    try:
        cf = config.split('//')
        data = json.loads(base64.b64decode(cf[1]))
        uuid = data.get('id')
        return await find_uuid(uuid)
    except:
        return None


async def find_uuid(target):
    global last_users
    if len(last_users) == 0:
        last_users = await get_users()
    for user in last_users:
        uuid = user['proxies']['vmess'].get('id')
        username = user.get('username')
        if uuid == target:
            return await get_user(username)


async def read_loc(configs, loc):
    result = []
    for config in configs:
        cf = config.split('//')
        if cf[0].strip() == 'vless:':
            cf_domain = cf[1].split('@')[1].split(':')[0]
            for domain in settings['server']['domains']:
                if domain == cf_domain:
                    if settings['server']['domains'][domain] == loc:
                        result.append(config)
        else:
            data = json.loads(base64.b64decode(cf[1]))
            cf_domain = data.get('add')
            for domain in settings['server']['domains']:
                if domain == cf_domain:
                    if settings['server']['domains'][domain] == loc:
                        result.append(config)
    return result


async def get_link(config):
    try:
        with open("config.txt", "w") as f:
            f.write(config)
        url = "https://file.io/"
        files = {"file": open("config.txt", "r")}
        r = requests.post(url, files=files)
        link = r.json().get("link")
        return link
    except:
        print("Couldn't upload")