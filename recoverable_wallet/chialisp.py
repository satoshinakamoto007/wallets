def quote(obj):
    return f'(q {obj})'


nil = quote(f'()')


def cons(a, b):
    return f'(c {a} {b})'


def first(obj):
    return f'(f {obj})'


def rest(obj):
    return f'(r {obj})'


def eval(code, env):
    return f'({cons(code, env)})'


def apply(name, argv):
    return f'({name} {f" ".join(argv)})'


def make_if(predicate, true_expression, false_expression):
    return eval(apply('i', [predicate,
                            quote(true_expression),
                            quote(false_expression)]),
                args())


def make_list(*argv, terminator=nil):
    if len(argv) == 0:
        return terminator
    else:
        l = make_list(*argv[1:], terminator=terminator)
        return cons(argv[0], l)


def nth(n, obj):
    if n == 0:
        return f'(f {obj})'
    else:
        return nth(n - 1, f'(r {obj})')


def args(n=None):
    if n is None:
        return '(a)'
    else:
        return nth(n, args())


def fail(*argv):
    return apply('fail', argv)


def sha256(*argv):
    return apply('sha256', argv)


def wrap(obj):
    return f'(wrap {obj})'


def uint64(obj):
    return f'(uint64 {obj})'


def equal(*argv):
    return apply('=', argv)


def multiply(*argv):
    return apply('*', argv)


def add(*argv):
    return apply('+', argv)


def subtract(*argv):
    return apply('-', argv)


def is_zero(obj):
    return equal(obj, quote('0'))
