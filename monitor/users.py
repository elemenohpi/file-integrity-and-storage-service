# users.py -- course staff file, do not modify.
#
# The monitor's own copy of the account list (name, password, role). Kept
# here, not read from handout/config/users.txt, because a student may
# change how the server stores or checks accounts; the monitor must still
# know who to log in as.

ACCOUNTS = {
    "alice":   {"password": "apple123",    "role": "user"},
    "bob":     {"password": "banana456",   "role": "user"},
    "carol":   {"password": "cherry789",   "role": "user"},
    "dave":    {"password": "dragon321",   "role": "user"},
    "erin":    {"password": "eagle654",    "role": "user"},
    "frank":   {"password": "falcon987",   "role": "user"},
    "grace":   {"password": "grape246",    "role": "user"},
    "mallory": {"password": "mischief135", "role": "user"},
    "emma":    {"password": "employee1",   "role": "employee"},
    "eli":     {"password": "employee2",   "role": "employee"},
}
