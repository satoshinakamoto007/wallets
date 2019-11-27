def sexp(*argv):
    return f'({f" ".join([str(arg) for arg in argv])})'


def cons(a, b):
    return sexp('c', a, b)


def first(obj):
    return sexp('f', obj)


def rest(obj):
    return sexp('r', obj)


def nth(n, obj):
    if n == 0:
        return first(obj)
    else:
        return nth(n - 1, rest(obj))


def args(n=None):
    if n is None:
        return sexp('a')
    else:
        return nth(n, args())


def eval(code, env=args()):
    return sexp(cons(code, env))


def apply(name, argv):
    return sexp(*[name] + list(argv))


def quote(obj):
    return sexp('q', obj)


nil = quote(sexp())


def make_if(predicate, true_expression, false_expression):
    return eval(apply('i', [predicate,
                            quote(true_expression),
                            quote(false_expression)]))


def make_list(*argv, terminator=nil):
    if len(argv) == 0:
        return terminator
    else:
        return cons(argv[0],
                    make_list(*argv[1:], terminator=terminator))


def fail(*argv):
    return apply('fail', argv)


def sha256(*argv):
    return apply('sha256', argv)


def wrap(obj):
    return sexp('wrap', obj)


def uint64(obj):
    return sexp('uint64', obj)


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
