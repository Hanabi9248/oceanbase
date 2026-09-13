"""Run against an explicitly prepared disposable MySQL-mode OceanBase tenant.

The default 32-character checks passed against patched observer. Requires a client;
credentials, if needed, belong in its defaults file, not command-line arguments.
"""

import argparse
import json
import os
import re
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--defaults-file")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--expected-limit", type=int, choices=(32, 64), required=True)
    parser.add_argument("--compatibility-version")
    args = parser.parse_args()
    command = [args.client]
    if args.defaults_file:
        command.append("--defaults-file=" + args.defaults_file)
    command += ["--host=127.0.0.1", "--protocol=TCP", "--port=" + str(args.port),
                "--user=" + args.user, "--batch", "--skip-column-names"]
    prefix = "grant_reg_" + uuid.uuid4().hex[:8]
    database = prefix
    accounts = []

    def sql(statement, error=None):
        result = subprocess.run(command + ["--execute", statement],
                                capture_output=True, text=True, timeout=90)
        if error is None:
            if result.returncode:
                raise AssertionError(result.stderr)
        elif result.returncode == 0 or not re.search(r"ERROR " + str(error) + r"\b", result.stderr):
            raise AssertionError("Expected error %s: %s" % (error, result.stderr))
        return result

    def account(length, label):
        name = (prefix + label).ljust(length, "x")
        assert len(name.encode("ascii")) == length
        accounts.append(name)
        return name

    previous_version = None
    if args.compatibility_version:
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("Compatibility changes require the disposable Actions fixture")
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", args.compatibility_version):
            raise ValueError("Expected a four-part compatibility version")
        previous_version = sql("SELECT @@GLOBAL.ob_compatibility_version").stdout.strip()
        if not re.fullmatch(r"[0-9.]+", previous_version):
            raise ValueError("Unexpected existing compatibility version")
    print(json.dumps({"server": sql("SELECT VERSION()").stdout.strip(),
                      "expected_limit": args.expected_limit}))
    try:
        if previous_version is not None:
            sql("SET GLOBAL ob_compatibility_version='" + args.compatibility_version + "'")
            print(json.dumps({"compatibility_version": sql(
                "SELECT @@GLOBAL.ob_compatibility_version").stdout.strip()}))
        sql("CREATE DATABASE `" + database + "`")
        sql("CREATE TABLE `" + database + "`.t (id INT)")
        # CREATE USER is the independent control for the tenant's active limit.
        lengths = sorted({32, 33, args.expected_limit, args.expected_limit + 1})
        for index, length in enumerate(lengths):
            name = account(length, "c" + str(index))
            expected = 1470 if length > args.expected_limit else None
            sql("CREATE USER '" + name + "' IDENTIFIED BY 'Regression-Only9!'", expected)
        for index, scope in enumerate(("*.*", "`" + database + "`.*", "`" + database + "`.t")):
            for length in lengths:
                name = account(length, "g" + str(index) + str(length))
                expected = 1470 if length > args.expected_limit else None
                result = sql("GRANT SELECT ON " + scope + " TO '" + name +
                             "' IDENTIFIED BY 'Regression-Only9!'", expected)
                if expected and not re.search(r"\b" + str(args.expected_limit) + r"\b", result.stderr):
                    raise AssertionError("Length diagnostic did not report the active limit")
                count = sql("SELECT COUNT(*) FROM mysql.user WHERE User='" + name + "'").stdout.strip()
                if count != ("0" if expected else "1"):
                    raise AssertionError("Unexpected persisted account: " + name + " count=" + count)
                if not expected:
                    # Existing-account grants without IDENTIFIED BY must still work.
                    sql("GRANT SELECT ON " + scope + " TO '" + name + "'")
                print(json.dumps({"scope": scope, "length": length, "result": "PASS"}))
    finally:
        # Names are unique to this invocation; never remove pre-existing accounts.
        try:
            for name in accounts:
                sql("DROP USER IF EXISTS '" + name + "'")
            sql("DROP DATABASE IF EXISTS `" + database + "`")
        finally:
            if previous_version is not None:
                sql("SET GLOBAL ob_compatibility_version='" + previous_version + "'")


if __name__ == "__main__":
    main()
