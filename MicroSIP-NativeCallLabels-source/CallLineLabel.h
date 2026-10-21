/*
 * MicroSIP Native Call Labels (source integration)
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Resolve the label of the active SIP account (MicroSIP.ini [AccountN] label=).
 * Falls back to username@domain via GetAccountLabel when label is empty.
 */
#pragma once

#include "settings.h"

namespace CallLineLabel
{
    inline CString Read()
    {
        if (accountSettings.accountId) {
            return GetAccountLabel(&accountSettings.account, accountSettings.accountId);
        }
        return GetAccountLabel(&accountSettings.accountLocal, 0);
    }
}
