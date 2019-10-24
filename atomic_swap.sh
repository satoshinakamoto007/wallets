trap "exit" INT TERM
trap "kill 0" EXIT
. activate

#Run Ledger in background, but make sure to kill it when terminal is closed
ledger-sim &> out &
sleep 1
python as_wallet_runnable.py

for job in $(jobs -p); do
    wait $job
done
