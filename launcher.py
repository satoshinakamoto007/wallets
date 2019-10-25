import asyncio
from runnables.wallet_runnable import Runnable
from runnables.AP_wallet_runnable import AP_Runnable
from runnables.as_wallet_runnable import AS_Runnable
from decorations import prompt, selectable

print("Select wallet type: ")
print(selectable + " 1: Default")
print(selectable + " 2: Authorised Payee")
print(selectable + " 3: Atomic Swaps")
choice = input(prompt)
run = asyncio.get_event_loop().run_until_complete
if choice == "1":
    runnable = Runnable()
elif choice == "2":
    runnable = AP_Runnable()
elif choice == "3":
    runnable = AS_Runnable()
run(runnable.main())
