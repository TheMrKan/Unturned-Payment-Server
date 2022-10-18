import db as database
from prettytable import PrettyTable

dbm: database.DatabaseManager = database.DatabaseManager("database.sqlite3")

invoices = database.__get_all_invoices(dbm.connection, dbm.cursor)
users = database.__get_all_users(dbm.connection, dbm.cursor)

table = PrettyTable()
table.field_names = ["ID", "User Token", "Status", "Sum", "Credited", "Created", "Payed", "Auto-withdraw", "Comment"]

filtered_invoices = [r for r in invoices if r[2] == "withdrawed"]

table.sortby = "Created"
table.add_rows(filtered_invoices)
table.del_column("Auto-withdraw")
table.del_column("User Token")
table.add_row(("Всего: ", "", sum([r[3] for r in invoices if r[2] == "withdrawed"]),
               sum([r[4] for r in invoices if r[2] == "withdrawed"]), "9", "", ""))

print(table)

input("")
